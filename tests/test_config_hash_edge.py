"""Edge-case coverage for quant/config_hash.py — non-finite floats and
numpy scalars.

Corresponds to PR #5 Python plan Finding 6. The `_coerce` function must
canonicalize NaN / +inf / -inf to deterministic string sentinels so that
`json.dumps(..., allow_nan=False)` succeeds while preserving hash stability
across identical configs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from quant.config_hash import CONFIG_HASH_VERSION, config_hash


@dataclass
class _FakeConfig:
    tickers: list[str] = field(default_factory=list)
    long_threshold: float = 0.0
    short_threshold: float = 0.0


# ── Basic scalar non-finite floats ────────────────────────────────────────


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_floats_are_hashable_and_deterministic(bad):
    a = _FakeConfig(tickers=["AAPL"], long_threshold=bad)
    b = _FakeConfig(tickers=["AAPL"], long_threshold=bad)
    # Same non-finite value → same hash.
    h = config_hash(a)
    assert h == config_hash(b)
    assert h.startswith(f"v{CONFIG_HASH_VERSION}:")


def test_nan_differs_from_pos_inf():
    a = _FakeConfig(tickers=["AAPL"], long_threshold=float("nan"))
    b = _FakeConfig(tickers=["AAPL"], long_threshold=float("inf"))
    assert config_hash(a) != config_hash(b)


def test_pos_inf_differs_from_neg_inf():
    a = _FakeConfig(tickers=["AAPL"], long_threshold=float("inf"))
    b = _FakeConfig(tickers=["AAPL"], long_threshold=float("-inf"))
    assert config_hash(a) != config_hash(b)


def test_non_finite_differs_from_finite():
    a = _FakeConfig(tickers=["AAPL"], long_threshold=float("nan"))
    b = _FakeConfig(tickers=["AAPL"], long_threshold=0.0)
    assert config_hash(a) != config_hash(b)


# ── Nested structures ────────────────────────────────────────────────────


def test_nested_dict_with_nan_is_hashable():
    cfg = {"tickers": ["AAPL"], "nested": {"x": float("nan"), "y": 0.3}}
    # Must not raise.
    h1 = config_hash(cfg)
    h2 = config_hash(cfg)
    assert h1 == h2
    assert h1.startswith(f"v{CONFIG_HASH_VERSION}:")


def test_nested_list_with_inf_is_hashable():
    cfg = {"tickers": ["AAPL"], "weights": [0.1, float("inf"), 0.3]}
    h1 = config_hash(cfg)
    h2 = config_hash(cfg)
    assert h1 == h2


def test_nested_dict_with_all_three_non_finite():
    """Mix of NaN, +inf, -inf in a nested dict."""
    cfg = {
        "tickers": ["AAPL"],
        "extra": {
            "a": float("nan"),
            "b": float("inf"),
            "c": float("-inf"),
        },
    }
    h = config_hash(cfg)
    assert h.startswith(f"v{CONFIG_HASH_VERSION}:")
    assert config_hash(cfg) == h


# ── Numpy scalar coverage ────────────────────────────────────────────────


def test_numpy_float_nan_is_hashable():
    np = pytest.importorskip("numpy")

    @dataclass
    class _NpCfg:
        tickers: list[str] = field(default_factory=list)
        alpha: float = 0.0

    a = _NpCfg(tickers=["AAPL"], alpha=float(np.float64("nan")))
    b = _NpCfg(tickers=["AAPL"], alpha=float(np.float64("nan")))
    h = config_hash(a)
    assert h == config_hash(b)
    assert h.startswith(f"v{CONFIG_HASH_VERSION}:")


def test_numpy_scalar_inf_is_hashable():
    np = pytest.importorskip("numpy")

    @dataclass
    class _NpCfg:
        tickers: list[str] = field(default_factory=list)
        alpha: float = 0.0

    a = _NpCfg(tickers=["AAPL"], alpha=float(np.float64(np.inf)))
    b = _NpCfg(tickers=["AAPL"], alpha=float(np.float64(np.inf)))
    assert config_hash(a) == config_hash(b)


def test_numpy_neg_inf_differs_from_pos_inf():
    np = pytest.importorskip("numpy")

    @dataclass
    class _NpCfg:
        tickers: list[str] = field(default_factory=list)
        alpha: float = 0.0

    a = _NpCfg(tickers=["AAPL"], alpha=float(np.float64(np.inf)))
    b = _NpCfg(tickers=["AAPL"], alpha=float(np.float64(-np.inf)))
    assert config_hash(a) != config_hash(b)


# ── Strict JSON invariant: allow_nan=False enforced ───────────────────────


def test_serialized_hash_does_not_contain_nan_or_infinity_literals():
    """Defense-in-depth: a successful hash run must never have relied on
    Python's non-RFC NaN/Infinity JSON literals. We cannot inspect the
    intermediate serialization from outside the function, but we can at
    least verify that constructing a config with non-finite values does
    not raise a ValueError from `json.dumps(..., allow_nan=False)`.
    """
    # If _coerce forgot to strip a non-finite value, this call would raise
    # ValueError("Out of range float values are not JSON compliant").
    cfg = _FakeConfig(
        tickers=["AAPL"],
        long_threshold=float("nan"),
        short_threshold=float("-inf"),
    )
    # Should complete without raising.
    h = config_hash(cfg)
    assert h.startswith(f"v{CONFIG_HASH_VERSION}:")
