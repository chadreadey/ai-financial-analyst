import json
import pytest
from unittest.mock import patch, MagicMock
from quant.timesfm import cache


@pytest.fixture(autouse=True)
def reset_cache():
    cache._redis_client = None
    cache._redis_checked = False
    yield
    cache._redis_client = None
    cache._redis_checked = False


def _make_fake_redis():
    store = {}

    class FakeRedis:
        def ping(self):
            return True

        def keys(self, pattern):
            import fnmatch

            return [k for k in store if fnmatch.fnmatch(k, pattern)]

        def mget(self, keys):
            return [store.get(k) for k in keys]

        def setex(self, key, ttl, value):
            store[key] = value

    return FakeRedis(), store


def test_put_and_get_signals():
    fake, store = _make_fake_redis()
    with (
        patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379"}),
        patch("redis.Redis.from_url", return_value=fake),
    ):
        assert cache.put_signals("AAPL", "price_forecast", {"trend": "bullish"})

    cache._redis_checked = False
    cache._redis_client = None
    with (
        patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379"}),
        patch("redis.Redis.from_url", return_value=fake),
    ):
        result = cache.get_signals("AAPL")
        assert result is not None
        assert "price_forecast" in result
        assert result["price_forecast"]["trend"] == "bullish"


def test_get_signals_missing_key():
    fake, store = _make_fake_redis()
    with (
        patch.dict("os.environ", {"REDIS_URL": "redis://localhost:6379"}),
        patch("redis.Redis.from_url", return_value=fake),
    ):
        result = cache.get_signals("MSFT")
        assert result is None


def test_graceful_degradation_no_url():
    with patch.dict("os.environ", {"REDIS_URL": ""}):
        assert cache.put_signals("AAPL", "price_forecast", {"x": 1}) is False
        assert cache.get_signals("AAPL") is None


def test_graceful_degradation_connection_error():
    def raise_err(*a, **kw):
        raise ConnectionError("nope")

    with (
        patch.dict("os.environ", {"REDIS_URL": "redis://bad:6379"}),
        patch("redis.Redis.from_url", side_effect=raise_err),
    ):
        assert cache.put_signals("AAPL", "price_forecast", {"x": 1}) is False
        cache._redis_checked = False
        assert cache.get_signals("AAPL") is None
