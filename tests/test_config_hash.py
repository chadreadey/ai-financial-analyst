"""Tests for quant/config_hash.py — deterministic config hashing for reproducibility."""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from quant.config_hash import CONFIG_HASH_VERSION, canonical_config, config_hash


@dataclass
class _FakeConfig:
    tickers: list[str] = field(default_factory=list)
    start_date: str = "2016-01-01"
    end_date: str = "2026-01-01"
    long_threshold: float = 0.20
    short_threshold: float = -0.40
    enable_regime_filter: bool = True
    max_long_positions: int = 10
    verbose: bool = False
    output_dir: str = "/tmp/x"


def test_hash_is_deterministic_and_version_prefixed():
    cfg = _FakeConfig(tickers=["AAPL", "MSFT"])
    h1 = config_hash(cfg)
    h2 = config_hash(cfg)
    assert h1 == h2
    assert h1.startswith(f"v{CONFIG_HASH_VERSION}:")
    assert len(h1.split(":")[1]) == 64


def test_ticker_order_does_not_change_hash():
    """`tickers` is semantically order-insensitive — same universe → same hash."""
    a = _FakeConfig(tickers=["AAPL", "MSFT", "GOOGL"])
    b = _FakeConfig(tickers=["GOOGL", "AAPL", "MSFT"])
    assert config_hash(a) == config_hash(b)


def test_excluded_fields_do_not_affect_hash():
    """Changing `verbose` or `output_dir` must not change the hash."""
    a = _FakeConfig(tickers=["AAPL"], verbose=False, output_dir="/tmp/a")
    b = _FakeConfig(tickers=["AAPL"], verbose=True, output_dir="/tmp/b")
    assert config_hash(a) == config_hash(b)


def test_result_affecting_field_changes_hash():
    """Changing a real knob (e.g. `long_threshold`) MUST change the hash."""
    a = _FakeConfig(tickers=["AAPL"], long_threshold=0.20)
    b = _FakeConfig(tickers=["AAPL"], long_threshold=0.25)
    assert config_hash(a) != config_hash(b)


def test_float_precision_neutralizes_floating_point_drift():
    """0.1 + 0.2 and 0.3 round identically at 10 decimals."""
    a = _FakeConfig(tickers=["AAPL"], long_threshold=0.1 + 0.2)
    b = _FakeConfig(tickers=["AAPL"], long_threshold=0.3)
    assert config_hash(a) == config_hash(b)


def test_dict_input_supported():
    cfg_dict = {"tickers": ["AAPL", "MSFT"], "long_threshold": 0.2}
    h = config_hash(cfg_dict)
    assert h.startswith(f"v{CONFIG_HASH_VERSION}:")


def test_canonical_config_sorts_keys_and_coerces_types():
    cfg = _FakeConfig(tickers=["ZZZ", "AAA"], long_threshold=0.123456789012345)
    canonical = canonical_config(cfg)
    keys = list(canonical.keys())
    assert keys == sorted(keys)
    assert canonical["tickers"] == ["AAA", "ZZZ"]
    assert canonical["long_threshold"] == round(0.123456789012345, 10)
    assert "verbose" not in canonical
    assert "output_dir" not in canonical


def test_extra_excluded_fields():
    """Callers can temporarily exclude additional fields."""
    a = _FakeConfig(tickers=["AAPL"], end_date="2026-01-01")
    b = _FakeConfig(tickers=["AAPL"], end_date="2026-04-01")
    assert config_hash(a) != config_hash(b)
    assert config_hash(a, extra_excluded=["end_date"]) == config_hash(b, extra_excluded=["end_date"])


def test_numpy_scalar_coercion():
    np = pytest.importorskip("numpy")

    @dataclass
    class _NpCfg:
        alpha: float = 0.0
        n: int = 0

    a = _NpCfg(alpha=float(np.float64(0.5)), n=int(np.int64(10)))
    b = _NpCfg(alpha=0.5, n=10)
    assert config_hash(a) == config_hash(b)


def test_datetime_coerced_to_iso_date():
    from datetime import datetime

    @dataclass
    class _DtCfg:
        run_start: str = ""

    a = _DtCfg(run_start=datetime(2026, 1, 15, 12, 34, 56).isoformat()[:10])
    b = _DtCfg(run_start="2026-01-15")
    assert config_hash(a) == config_hash(b)
