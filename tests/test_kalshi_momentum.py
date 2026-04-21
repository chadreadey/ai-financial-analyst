"""Tests for compute_macro_momentum in quant/kalshi_signal.py."""
import unittest
from unittest.mock import MagicMock, patch


class TestMacroMomentum(unittest.TestCase):

    def _make_client(self, current_markets, prior_markets):
        """Return a mock KalshiClient whose get_markets alternates current/prior."""
        client = MagicMock()
        # compute_macro_modifier calls get_markets for FED, CPI, JOBS (current)
        # then again for FED, CPI, JOBS (prior) → 6 calls total, interleaved by series.
        # We'll side_effect based on call count groups.
        call_count = {"n": 0}
        num_series = 3  # FED, CPI, JOBS

        def _get_markets(series_ticker, _date_override=None):
            call_count["n"] += 1
            if call_count["n"] <= num_series:
                return current_markets
            return prior_markets

        client.get_markets.side_effect = _get_markets
        return client

    def test_positive_momentum(self):
        """Prior modifier -0.3, current +0.2 → returns ~0.5."""
        from quant.kalshi_signal import compute_macro_momentum

        # We patch compute_macro_modifier to return controlled values
        with patch("quant.kalshi_signal.compute_macro_modifier") as mock_modifier:
            mock_modifier.side_effect = [0.2, -0.3]  # current, prior
            client = MagicMock()
            result = compute_macro_momentum(client)
            self.assertAlmostEqual(result, 0.5, places=5)

    def test_negative_momentum(self):
        """Prior +0.4, current -0.1 → returns -0.5."""
        from quant.kalshi_signal import compute_macro_momentum

        with patch("quant.kalshi_signal.compute_macro_modifier") as mock_modifier:
            mock_modifier.side_effect = [-0.1, 0.4]  # current, prior
            client = MagicMock()
            result = compute_macro_momentum(client)
            self.assertAlmostEqual(result, -0.5, places=5)

    def test_zero_when_no_change(self):
        """Prior and current equal → returns 0.0."""
        from quant.kalshi_signal import compute_macro_momentum

        with patch("quant.kalshi_signal.compute_macro_modifier") as mock_modifier:
            mock_modifier.side_effect = [0.3, 0.3]
            client = MagicMock()
            result = compute_macro_momentum(client)
            self.assertAlmostEqual(result, 0.0, places=5)

    def test_clips_to_bounds(self):
        """Delta > 1.0 clips to 1.0."""
        from quant.kalshi_signal import compute_macro_momentum

        with patch("quant.kalshi_signal.compute_macro_modifier") as mock_modifier:
            mock_modifier.side_effect = [1.0, -0.8]  # delta = 1.8 → clips to 1.0
            client = MagicMock()
            result = compute_macro_momentum(client)
            self.assertAlmostEqual(result, 1.0, places=5)

    def test_graceful_on_error(self):
        """Client raises exception → returns 0.0."""
        from quant.kalshi_signal import compute_macro_momentum

        with patch("quant.kalshi_signal.compute_macro_modifier") as mock_modifier:
            mock_modifier.side_effect = RuntimeError("network failure")
            client = MagicMock()
            result = compute_macro_momentum(client)
            self.assertEqual(result, 0.0)


if __name__ == "__main__":
    unittest.main()
