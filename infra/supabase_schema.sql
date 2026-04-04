-- =============================================================================
-- Supabase (PostgreSQL) schema for the AI Financial Analyst warehouse
--
-- Mirrors the SQLite schema from warehouse/db.py with the following additions:
--   - TIMESTAMPTZ for all timestamp columns (converted from REAL unix timestamps)
--   - updated_at triggers (standard Supabase pattern)
--   - Indexes tuned for the actual query patterns in WarehouseDB
--   - RLS enabled on all tables (policies left open for now — auth coming later)
--   - users + user_watchlists tables for future multi-tenancy
-- =============================================================================

-- ── helper: updated_at trigger function ──────────────────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- Core warehouse tables
-- =============================================================================

-- ── companies ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS companies (
    ticker              TEXT        PRIMARY KEY,
    cik                 TEXT        NOT NULL,
    name                TEXT        NOT NULL,
    last_accession      TEXT,
    bootstrapped_at     TIMESTAMPTZ,
    last_checked_at     TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- poll worker sweeps by staleness: ORDER BY last_checked_at ASC NULLS FIRST
CREATE INDEX IF NOT EXISTS idx_companies_last_checked_at
    ON companies (last_checked_at ASC NULLS FIRST);

CREATE OR REPLACE TRIGGER trg_companies_updated_at
    BEFORE UPDATE ON companies
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow all companies" ON companies FOR ALL USING (true) WITH CHECK (true);

-- ── filings ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS filings (
    ticker          TEXT        NOT NULL,
    accession       TEXT        NOT NULL,
    form            TEXT        NOT NULL,
    filing_date     DATE        NOT NULL,
    primary_doc     TEXT        NOT NULL DEFAULT '',
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, accession)
);

-- get_filings(): WHERE ticker = ? AND form IN (...) ORDER BY filing_date DESC
CREATE INDEX IF NOT EXISTS idx_filings_ticker_form_date
    ON filings (ticker, form, filing_date DESC);

CREATE OR REPLACE TRIGGER trg_filings_updated_at
    BEFORE UPDATE ON filings
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE filings ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow all filings" ON filings FOR ALL USING (true) WITH CHECK (true);

-- ── xbrl_facts ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS xbrl_facts (
    ticker          TEXT        NOT NULL,
    concept         TEXT        NOT NULL,
    unit            TEXT        NOT NULL,
    period_end      DATE        NOT NULL,
    value           DOUBLE PRECISION NOT NULL,
    form            TEXT,
    fiscal_year     INTEGER,
    fiscal_period   TEXT,
    filed_date      DATE,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, concept, unit, period_end, form)
);

-- get_xbrl_facts(): WHERE ticker = ? AND concept IN (...) ORDER BY period_end DESC
CREATE INDEX IF NOT EXISTS idx_xbrl_facts_ticker_concept_period
    ON xbrl_facts (ticker, concept, period_end DESC);

CREATE OR REPLACE TRIGGER trg_xbrl_facts_updated_at
    BEFORE UPDATE ON xbrl_facts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE xbrl_facts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow all xbrl_facts" ON xbrl_facts FOR ALL USING (true) WITH CHECK (true);

-- ── market_snapshots ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS market_snapshots (
    ticker          TEXT             NOT NULL,
    as_of_date      DATE             NOT NULL,
    price           DOUBLE PRECISION,
    market_cap      DOUBLE PRECISION,
    pe_ttm          DOUBLE PRECISION,
    forward_pe      DOUBLE PRECISION,
    ps_ttm          DOUBLE PRECISION,
    ev_ebitda       DOUBLE PRECISION,
    beta            DOUBLE PRECISION,
    week52_high     DOUBLE PRECISION,
    week52_low      DOUBLE PRECISION,
    target_mean     DOUBLE PRECISION,
    recommendation  TEXT,
    ingested_at     TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, as_of_date)
);

-- get_market_snapshot(): WHERE ticker = ? ORDER BY as_of_date DESC LIMIT 1
CREATE INDEX IF NOT EXISTS idx_market_snapshots_ticker_date
    ON market_snapshots (ticker, as_of_date DESC);

CREATE OR REPLACE TRIGGER trg_market_snapshots_updated_at
    BEFORE UPDATE ON market_snapshots
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE market_snapshots ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow all market_snapshots" ON market_snapshots FOR ALL USING (true) WITH CHECK (true);

-- ── macro_series ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS macro_series (
    series_id       TEXT             NOT NULL,
    label           TEXT             NOT NULL,
    as_of_date      DATE             NOT NULL,
    value           DOUBLE PRECISION NOT NULL,
    ingested_at     TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ      NOT NULL DEFAULT NOW(),
    PRIMARY KEY (series_id, as_of_date)
);

-- get_macro_series(): WHERE series_id IN (...) ORDER BY as_of_date DESC
CREATE INDEX IF NOT EXISTS idx_macro_series_id_date
    ON macro_series (series_id, as_of_date DESC);

CREATE OR REPLACE TRIGGER trg_macro_series_updated_at
    BEFORE UPDATE ON macro_series
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE macro_series ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow all macro_series" ON macro_series FOR ALL USING (true) WITH CHECK (true);

-- ── filing_sections ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS filing_sections (
    ticker          TEXT        NOT NULL,
    accession       TEXT        NOT NULL,
    section_key     TEXT        NOT NULL,
    text            TEXT        NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, accession, section_key)
);

-- get_filing_section(): WHERE ticker = ? AND section_key = ?
CREATE INDEX IF NOT EXISTS idx_filing_sections_ticker_section_key
    ON filing_sections (ticker, section_key);

-- FK-style lookup on (ticker, accession) for embedder joins
CREATE INDEX IF NOT EXISTS idx_filing_sections_ticker_accession
    ON filing_sections (ticker, accession);

CREATE OR REPLACE TRIGGER trg_filing_sections_updated_at
    BEFORE UPDATE ON filing_sections
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE filing_sections ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow all filing_sections" ON filing_sections FOR ALL USING (true) WITH CHECK (true);

-- =============================================================================
-- Future multi-tenancy tables
-- =============================================================================

-- ── users ─────────────────────────────────────────────────────────────────────
-- Scaffold for Supabase Auth integration.
-- In production, id will reference auth.users(id) via a trigger or FK.
CREATE TABLE IF NOT EXISTS users (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT        NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE users ENABLE ROW LEVEL SECURITY;
-- Users can only see their own row; service role bypasses RLS.
CREATE POLICY "users can view own row" ON users
    FOR SELECT USING (id = auth.uid());
CREATE POLICY "users can update own row" ON users
    FOR UPDATE USING (id = auth.uid()) WITH CHECK (id = auth.uid());

-- ── user_watchlists ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_watchlists (
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ticker      TEXT        NOT NULL,
    added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, ticker)
);

CREATE INDEX IF NOT EXISTS idx_user_watchlists_user_id
    ON user_watchlists (user_id);

ALTER TABLE user_watchlists ENABLE ROW LEVEL SECURITY;
CREATE POLICY "users can manage own watchlist" ON user_watchlists
    FOR ALL USING (user_id = auth.uid()) WITH CHECK (user_id = auth.uid());
