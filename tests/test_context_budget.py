"""Tests for context_budget.trim_text."""

from context_budget import trim_text


def test_trim_text_under_limit():
    assert trim_text("hello", 100) == "hello"


def test_trim_text_exactly_at_limit():
    text = "a" * 50
    assert trim_text(text, 50) == text


def test_trim_text_over_limit():
    text = "a" * 100
    result = trim_text(text, 50)
    assert len(result) == 50
    assert result.endswith("\n...[trimmed]...")


def test_trim_text_custom_marker():
    text = "a" * 100
    result = trim_text(text, 20, marker="...")
    assert len(result) == 20
    assert result.endswith("...")


def test_trim_text_empty_string():
    assert trim_text("", 100) == ""


def test_trim_text_zero_limit():
    assert trim_text("hello", 0) == ""


def test_trim_text_negative_limit():
    assert trim_text("hello", -1) == ""


def test_trim_text_marker_longer_than_limit():
    result = trim_text("hello world", 5, marker="...[very long marker]...")
    assert len(result) <= 5 or result == "...[very long marker]..."
