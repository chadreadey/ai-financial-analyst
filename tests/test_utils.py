"""Tests for utils.format_money and utils.env_flag."""

import os

from utils import env_flag, format_money


class TestFormatMoney:
    def test_none_returns_na(self):
        assert format_money(None) == "N/A"

    def test_trillions(self):
        assert format_money(1.5e12) == "$1.50T"

    def test_billions(self):
        assert format_money(2.3e9) == "$2.30B"

    def test_millions(self):
        assert format_money(45.6e6) == "$45.6M"

    def test_small_value(self):
        assert format_money(1234) == "$1,234"

    def test_negative_billions(self):
        assert format_money(-3.2e9) == "$-3.20B"

    def test_no_abbreviation(self):
        result = format_money(1_500_000, abbreviate=False)
        assert result == "$1,500,000"

    def test_zero(self):
        assert format_money(0) == "$0"


class TestEnvFlag:
    def test_true_values(self, monkeypatch):
        for val in ("1", "true", "True", "TRUE", "yes", "on", " true "):
            monkeypatch.setenv("TEST_FLAG", val)
            assert env_flag("TEST_FLAG") is True

    def test_false_values(self, monkeypatch):
        for val in ("0", "false", "no", "off", "anything"):
            monkeypatch.setenv("TEST_FLAG", val)
            assert env_flag("TEST_FLAG") is False

    def test_unset_uses_default_true(self, monkeypatch):
        monkeypatch.delenv("TEST_FLAG", raising=False)
        assert env_flag("TEST_FLAG", default=True) is True

    def test_unset_uses_default_false(self, monkeypatch):
        monkeypatch.delenv("TEST_FLAG", raising=False)
        assert env_flag("TEST_FLAG", default=False) is False
