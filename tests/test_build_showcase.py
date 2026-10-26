import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_showcase  # noqa: E402


def _brief(conflicts):
    return {
        "run_at": "2026-01-01T00:00:00+00:00",
        "result": {
            "company_name": "X",
            "structured_verdict": {
                "verdict": "BUY",
                "conviction": "HIGH",
                "signal_conflicts": conflicts,
            },
        },
    }


def test_failed_ticker_exits_nonzero_and_leaves_index(tmp_path):
    (tmp_path / "index.json").write_text("OLD")

    def analyze(t):
        if t == "BAD":
            raise ValueError("boom")
        return _brief(["a_vs_b"])

    assert build_showcase.build(["OK", "BAD"], tmp_path, analyze=analyze) == 1
    assert (tmp_path / "index.json").read_text() == "OLD"
    assert (tmp_path / "OK.json").exists()


@pytest.mark.parametrize("retries,calls", [(0, 1), (1, 2)])
def test_retries(tmp_path, retries, calls):
    n = []

    def analyze(t):
        n.append(t)
        raise RuntimeError("x")

    assert build_showcase.build(["A"], tmp_path, retries=retries, analyze=analyze) == 1
    assert len(n) == calls


def test_success_writes_index(tmp_path):
    def analyze(t):
        return _brief(["c"] if t == "A" else [])

    assert build_showcase.build(["A", "B"], tmp_path, analyze=analyze) == 0
    idx = json.loads((tmp_path / "index.json").read_text())
    assert [b["ticker"] for b in idx["briefs"]] == ["A", "B"]
