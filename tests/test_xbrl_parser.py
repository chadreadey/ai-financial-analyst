"""Tests for XBRLParser with minimal sample data."""

from sec.xbrl_parser import XBRLParser


def _make_facts(concepts: dict) -> dict:
    """Build a minimal company_facts structure for testing."""
    us_gaap = {}
    for concept, entries in concepts.items():
        units = {"USD": []}
        for entry in entries:
            units["USD"].append({
                "end": entry["end"],
                "val": entry["val"],
                "accn": "0001234567-25-000001",
                "fy": entry.get("fy", 2024),
                "fp": entry.get("fp", "FY"),
                "form": entry.get("form", "10-K"),
                "filed": entry.get("filed", "2025-02-15"),
                "start": entry.get("start", ""),
            })
        us_gaap[concept] = {"units": units}
    return {"facts": {"us-gaap": us_gaap}}


class TestXBRLParser:
    def test_compute_metrics_empty(self):
        parser = XBRLParser({"facts": {"us-gaap": {}}})
        metrics = parser.compute_metrics()
        assert isinstance(metrics, dict)

    def test_compute_metrics_revenue(self):
        facts = _make_facts({
            "Revenues": [
                {"end": "2024-12-31", "start": "2024-01-01", "val": 100_000_000_000, "fy": 2024, "fp": "FY"},
                {"end": "2023-12-31", "start": "2023-01-01", "val": 90_000_000_000, "fy": 2023, "fp": "FY"},
            ]
        })
        parser = XBRLParser(facts)
        metrics = parser.compute_metrics()
        assert metrics.get("revenue") == 100_000_000_000

    def test_get_historical_revenue(self):
        facts = _make_facts({
            "Revenues": [
                {"end": "2024-12-31", "start": "2024-01-01", "val": 100e9, "fy": 2024, "fp": "FY"},
                {"end": "2023-12-31", "start": "2023-01-01", "val": 90e9, "fy": 2023, "fp": "FY"},
                {"end": "2022-12-31", "start": "2022-01-01", "val": 80e9, "fy": 2022, "fp": "FY"},
            ]
        })
        parser = XBRLParser(facts)
        history = parser.get_historical_revenue(years=3)
        assert isinstance(history, list)
        assert len(history) >= 2

    def test_to_summary_text(self):
        facts = _make_facts({
            "Revenues": [
                {"end": "2024-12-31", "val": 100e9, "fy": 2024, "fp": "FY"},
            ]
        })
        parser = XBRLParser(facts)
        metrics = parser.compute_metrics()
        text = parser.to_summary_text(metrics=metrics)
        assert isinstance(text, str)
        assert len(text) > 0
