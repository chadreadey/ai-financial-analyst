"""Tests for the assumption-log observability layer:
  - scripts/show_assumption_log.py (CLI viewer, resolution + filtering)
  - quant.assumption_audit configuration bridge / JSONL sink
  - cross_sectional instrumentation is inert (does not change outputs)
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_viewer():
    path = os.path.join(REPO, "scripts", "show_assumption_log.py")
    spec = importlib.util.spec_from_file_location("show_assumption_log", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def sample_log(tmp_path):
    recs = [
        {"assumption": "min_sample", "target": "sharpe", "status": "violated",
         "severity": "high", "message": "n=5 < 30", "evidence": {}, "context": {"module": "m"}},
        {"assumption": "no_lookahead", "target": "px", "status": "violated",
         "severity": "critical", "message": "future leak", "evidence": {}, "context": {}},
        {"assumption": "normality", "target": "z", "status": "pass",
         "severity": "medium", "message": "ok", "evidence": {}, "context": {}},
        {"assumption": "stationarity", "target": "p", "status": "skipped_insufficient_information",
         "severity": "high", "message": "statsmodels absent", "evidence": {}, "context": {}},
    ]
    p = tmp_path / "assumptions.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in recs) + "\n")
    return str(p)


class TestViewer:
    def test_load_records(self, sample_log):
        v = _load_viewer()
        recs = v.load_records(sample_log)
        assert len(recs) == 4

    def test_resolve_explicit_path(self, sample_log):
        v = _load_viewer()
        assert v.resolve_log_path(sample_log) == sample_log

    def test_resolve_env(self, sample_log, monkeypatch):
        v = _load_viewer()
        monkeypatch.setenv("ASSUMPTION_AUDIT_JSONL", sample_log)
        assert v.resolve_log_path(None) == sample_log

    def test_main_runs_and_filters(self, sample_log, monkeypatch, capsys):
        v = _load_viewer()
        monkeypatch.setattr(sys, "argv",
                            ["show", "--path", sample_log, "--status", "violated"])
        rc = v.main()
        out = capsys.readouterr().out
        assert rc == 0
        assert "VIOLATED=2" in out
        assert "no_lookahead" in out

    def test_main_severity_filter(self, sample_log, monkeypatch, capsys):
        v = _load_viewer()
        monkeypatch.setattr(sys, "argv",
                            ["show", "--path", sample_log, "--severity", "critical"])
        v.main()
        out = capsys.readouterr().out
        assert "no_lookahead" in out
        assert "min_sample" not in out  # high < critical filtered out

    def test_main_missing_file(self, tmp_path, monkeypatch, capsys):
        v = _load_viewer()
        missing = str(tmp_path / "nope.jsonl")
        monkeypatch.setattr(sys, "argv", ["show", "--path", missing])
        rc = v.main()
        assert rc == 2


class TestConfigBridge:
    def test_env_overrides(self, monkeypatch, tmp_path):
        import quant.assumption_audit as aa
        monkeypatch.setenv("ASSUMPTION_AUDIT_ENABLED", "0")
        p = str(tmp_path / "x.jsonl")
        monkeypatch.setenv("ASSUMPTION_AUDIT_JSONL", p)
        enabled, jsonl = aa._resolve_default_config()
        assert enabled is False
        assert jsonl == p

    def test_configure_default_log(self, tmp_path):
        import quant.assumption_audit as aa
        aa.reset_audit_log()
        path = str(tmp_path / "sink.jsonl")
        log = aa.configure_default_log(enabled=True, jsonl_path=path)
        log.min_sample("x", n=5, min_n=30)  # violated -> should stream to disk
        assert os.path.exists(path)
        assert "violated" in open(path).read()
        aa.reset_audit_log()


class TestInstrumentationInert:
    def test_audit_hook_never_raises(self):
        """The instrumentation hook resolves to a log-or-None and never raises.
        (That the normalization *output* is unchanged is covered end-to-end by
        tests/test_cross_sectional.py, which passes with the hook in place.)"""
        from quant import cross_sectional as cs
        hook = cs._get_assumption_log()
        assert hook is None or hasattr(hook, "no_silent_zeros")

    def test_disabled_hook_is_none(self, monkeypatch):
        import quant.assumption_audit as aa
        from quant import cross_sectional as cs
        aa.reset_audit_log()
        monkeypatch.setenv("ASSUMPTION_AUDIT_ENABLED", "0")
        aa.reset_audit_log()  # re-resolve config with env applied
        assert cs._get_assumption_log() is None
        aa.reset_audit_log()
