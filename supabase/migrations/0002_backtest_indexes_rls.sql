-- =============================================================================
-- Migration 0002: backtest table index corrections and RLS hardening
--
-- Applies to: backtest_events, backtest_runs, backtest_combinations,
--             backtest_trades, backtest_events (RLS only for the last three)
--
-- Prerequisites: 0001_backtest_tables.sql must be applied.
-- Downtime: none (index CREATE/DROP and policy changes do not lock tables).
-- =============================================================================

-- ── Finding 3: Replace (run_id, created_at) index with (run_id, id) ──────────

DROP INDEX IF EXISTS idx_backtest_events_run_time;

CREATE INDEX IF NOT EXISTS idx_backtest_events_run_id
    ON backtest_events (run_id, id);

-- ── Finding 7: Restrict RLS to service_role only ──────────────────────────────

DROP POLICY IF EXISTS "allow all backtest_runs" ON backtest_runs;
CREATE POLICY "service_role_only_backtest_runs"
    ON backtest_runs FOR ALL
    USING  (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

DROP POLICY IF EXISTS "allow all backtest_combinations" ON backtest_combinations;
CREATE POLICY "service_role_only_backtest_combinations"
    ON backtest_combinations FOR ALL
    USING  (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

DROP POLICY IF EXISTS "allow all backtest_trades" ON backtest_trades;
CREATE POLICY "service_role_only_backtest_trades"
    ON backtest_trades FOR ALL
    USING  (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');

DROP POLICY IF EXISTS "allow all backtest_events" ON backtest_events;
CREATE POLICY "service_role_only_backtest_events"
    ON backtest_events FOR ALL
    USING  (auth.role() = 'service_role')
    WITH CHECK (auth.role() = 'service_role');
