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


# ── trim_middle ───────────────────────────────────────────────────────

from context_budget import trim_middle  # noqa: E402


def test_trim_middle_under_limit_unchanged():
    assert trim_middle("hello", 100, tail_chars=10) == "hello"


def test_trim_middle_keeps_signal_score_tail():
    report = "prose " * 1000 + "\nSIGNAL_SCORE: 0.42"
    result = trim_middle(report, 500, tail_chars=100, marker="[cut]")
    assert len(result) == 500
    assert result.endswith("SIGNAL_SCORE: 0.42")
    assert result.startswith("prose ")
    assert "[cut]" in result


def test_trim_middle_tail_larger_than_budget():
    result = trim_middle("a" * 50 + "TAIL", 10, tail_chars=100, marker="..")
    assert len(result) == 10
    assert result == "..aaaaTAIL"


def test_trim_middle_zero_limit():
    assert trim_middle("hello", 0, tail_chars=3) == ""
