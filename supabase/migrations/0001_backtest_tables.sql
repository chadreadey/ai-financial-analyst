-- =============================================================================
-- Supabase (PostgreSQL) schema for Modal CPCV backtesting
--
-- Complements infra/supabase_schema.sql (warehouse tables). These tables are
-- written by the Modal CPCV orchestrator (modal_app/dispatcher.py) via the
-- backend/supabase_backtest.py wrapper (PostgREST over urllib).
--
-- Four tables:
--   backtest_runs          — one row per dispatched CPCV run (run_id = PK)
--   backtest_combinations  — one row per (run_id, combo_idx)
--   backtest_trades        — one row per individual trade inside a combo
--   backtest_events        — structured event stream (run_started, combo_completed, ...)
--
-- RLS policies follow the existing pattern: permissive "allow all" until auth
-- lands. Service-role key bypasses RLS anyway.
-- =============================================================================

-- ── helper: updated_at trigger function (idempotent; already defined in warehouse schema) ──
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- backtest_runs — one row per CPCV run
-- =============================================================================
CREATE TABLE IF NOT EXISTS backtest_runs (
    run_id              TEXT        PRIMARY KEY,
    config_hash         TEXT        NOT NULL,
    git_sha             TEXT        NOT NULL,
    status              TEXT        NOT NULL DEFAULT 'queued',   -- queued | running | complete | degraded | failed
    universe            TEXT,
    n_groups            INTEGER,
    n_test_groups       INTEGER,
    n_combinations      INTEGER,
    n_completed         INTEGER     DEFAULT 0,
    n_skipped           INTEGER     DEFAULT 0,
    n_failed            INTEGER     DEFAULT 0,
    median_oos_sharpe   NUMERIC,
    oos_sharpe_min      NUMERIC,
    oos_sharpe_max      NUMERIC,
    pbo                 NUMERIC,
    deflated_sharpe     NUMERIC,
    config_json         JSONB       NOT NULL,
    metrics_json        JSONB,
    error               TEXT,
    modal_call_id       TEXT,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Lookup by config_hash powers the dedup pill ("this config ran 3× before").
CREATE INDEX IF NOT EXISTS idx_backtest_runs_config_hash
    ON backtest_runs (config_hash, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_backtest_runs_status
    ON backtest_runs (status, started_at DESC);

CREATE OR REPLACE TRIGGER trg_backtest_runs_updated_at
    BEFORE UPDATE ON backtest_runs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE backtest_runs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow all backtest_runs" ON backtest_runs FOR ALL USING (true) WITH CHECK (true);

-- =============================================================================
-- backtest_combinations — per-combo summary row
-- =============================================================================
CREATE TABLE IF NOT EXISTS backtest_combinations (
    run_id              TEXT        NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    combo_idx           INTEGER     NOT NULL,
    status              TEXT        NOT NULL DEFAULT 'complete',  -- complete | skipped | error
    train_indices       INTEGER[],
    test_indices        INTEGER[],
    oos_sharpe          NUMERIC,
    return_pct          NUMERIC,
    n_trades            INTEGER,
    n_test_dates        INTEGER,
    elapsed_seconds     NUMERIC,
    git_sha             TEXT,
    error               TEXT,
    gates_json          JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, combo_idx)
);

CREATE INDEX IF NOT EXISTS idx_backtest_combinations_run
    ON backtest_combinations (run_id, oos_sharpe DESC NULLS LAST);

ALTER TABLE backtest_combinations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow all backtest_combinations" ON backtest_combinations FOR ALL USING (true) WITH CHECK (true);

-- =============================================================================
-- backtest_trades — per-trade detail for UI drill-down
-- =============================================================================
CREATE TABLE IF NOT EXISTS backtest_trades (
    run_id                  TEXT        NOT NULL REFERENCES backtest_runs(run_id) ON DELETE CASCADE,
    combo_idx               INTEGER     NOT NULL,
    trade_idx               INTEGER     NOT NULL,      -- 0..n-1 within (run_id, combo_idx)
    ticker                  TEXT        NOT NULL,
    direction               TEXT        NOT NULL,      -- LONG | SHORT
    entry_date              DATE        NOT NULL,
    exit_date               DATE,
    entry_price             NUMERIC,
    exit_price              NUMERIC,
    pnl_dollar              NUMERIC,
    pnl_pct                 NUMERIC,
    holding_days            INTEGER,
    exit_reason             TEXT,
    composite_score         NUMERIC,
    regime_at_entry         TEXT,
    signals_at_entry_json   JSONB,                     -- full SignalVector snapshot (may be NULL)
    flags_json              JSONB,                     -- position flags (e.g. hedge_etf:risk_off)
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (run_id, combo_idx, trade_idx)
);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_ticker
    ON backtest_trades (run_id, ticker);

CREATE INDEX IF NOT EXISTS idx_backtest_trades_run_combo
    ON backtest_trades (run_id, combo_idx);

ALTER TABLE backtest_trades ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow all backtest_trades" ON backtest_trades FOR ALL USING (true) WITH CHECK (true);

-- =============================================================================
-- backtest_events — structured progress + error stream
-- =============================================================================
CREATE TABLE IF NOT EXISTS backtest_events (
    id          BIGSERIAL   PRIMARY KEY,
    run_id      TEXT        NOT NULL,   -- no FK so events survive if run row is rolled back mid-dispatch
    kind        TEXT        NOT NULL,   -- run_started | run_completed | run_failed | run_degraded
                                        -- combo_started | combo_completed | combo_failed | combo_skipped
    combo_idx   INTEGER,
    payload     JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_backtest_events_run_time
    ON backtest_events (run_id, created_at);

ALTER TABLE backtest_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "allow all backtest_events" ON backtest_events FOR ALL USING (true) WITH CHECK (true);
