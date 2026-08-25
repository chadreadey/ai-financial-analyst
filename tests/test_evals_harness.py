"""
Tests for the eval harness itself: datasets, cassettes, reporting, gating, and
the extraction behaviour the graders depend on.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from evals import contracts
from evals.checks import CheckResult, Sample, extract_pattern_vector, extract_structured
from evals.dataset import (
    AgentCase,
    SynthesisCase,
    load_agent_cases,
    load_synthesis_cases,
)
from evals.replay import (
    CASSETTE_VERSION,
    Cassette,
    CassetteMiss,
    CassetteProvider,
    open_cassette,
    request_key,
)
from evals.report import EvalReport, Gate, compare_to_baseline
from evals.runner import AGENT_REGISTRY, RunConfig, run_agent_suite, run_synthesis_suite
from evals.seed import SEED_MODEL, SEED_PROVIDER, fixture_path, load_fixture
from llm import LLMProvider
from models import AnalysisData


# ── dataset integrity ──────────────────────────────────────────────────────


def test_synthesis_cases_load():
    cases = load_synthesis_cases()
    assert cases
    assert len({c.id for c in cases}) == len(cases)


def test_agent_cases_load():
    cases = load_agent_cases()
    assert cases
    assert len({c.id for c in cases}) == len(cases)


def test_every_case_has_a_fixture_response():
    for case in [*load_synthesis_cases(), *load_agent_cases()]:
        assert fixture_path(case.id).exists(), (
            f"{case.id} has no fixture response; run `python -m evals record` or "
            f"author {fixture_path(case.id)}"
        )


def test_agent_case_agents_are_registered():
    for case in load_agent_cases():
        assert case.agent in AGENT_REGISTRY, f"{case.id}: unknown agent {case.agent!r}"


def test_agent_case_payloads_are_valid_analysis_data():
    for case in load_agent_cases():
        data = AnalysisData.model_validate(case.analysis_data)
        assert data.ticker


def test_synthesis_case_signals_are_known():
    for case in load_synthesis_cases():
        for report in case.agent_reports:
            assert report.signal in contracts.SIGNAL_WEIGHTS, (
                f"{case.id}: {report.signal!r} is not a synthesis signal"
            )


def test_dataset_covers_every_verdict_band():
    """A suite that never produces a SELL cannot detect a SELL regression."""
    verdicts = {
        case.expected_decision().verdict
        for case in load_synthesis_cases()
        if case.has_complete_signal_scores()
    }
    assert {"STRONG BUY", "BUY", "HOLD", "SELL"} <= verdicts, (
        f"uncovered verdict bands: {set(contracts.VERDICTS) - verdicts}"
    )


def test_dataset_exercises_the_adverse_macro_multiplier():
    cases = load_synthesis_cases()
    damped = [
        c
        for c in cases
        if (c.signal_scores().get("macro") or 0) <= contracts.ADVERSE_MACRO_THRESHOLD
    ]
    assert damped, "no case triggers the macro regime multiplier"

    case = damped[0]
    scores = case.signal_scores()
    raw = sum(v * contracts.SIGNAL_WEIGHTS[k] for k, v in scores.items())
    damped_score = case.expected_decision().weighted_score
    # The multiplier must actually change the verdict, or the case proves nothing.
    assert contracts.verdict_for_score(raw) != contracts.verdict_for_score(damped_score)


def test_duplicate_case_ids_are_rejected(tmp_path):
    path = tmp_path / "dupes.jsonl"
    row = {
        "id": "dupe",
        "ticker": "X",
        "company_name": "X Corp",
        "agent_reports": [],
    }
    path.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate eval case id"):
        load_synthesis_cases(path)


def test_malformed_jsonl_reports_the_line_number(tmp_path):
    path = tmp_path / "broken.jsonl"
    valid = json.dumps(
        {"id": "ok", "ticker": "X", "company_name": "X Corp", "agent_reports": []}
    )
    path.write_text(f"{valid}\nnot json\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"broken\.jsonl:2 is not valid JSON"):
        load_synthesis_cases(path)


def test_invalid_case_reports_the_line_number(tmp_path):
    path = tmp_path / "invalid.jsonl"
    path.write_text('{"id": "missing-fields"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match=r"invalid\.jsonl:1 is not a valid case"):
        load_synthesis_cases(path)


# ── ground truth derivation ────────────────────────────────────────────────


def _case(**overrides) -> SynthesisCase:
    base = {
        "id": "t",
        "ticker": "T",
        "company_name": "T Corp",
        "agent_reports": [
            {"agent_name": "DCF Analyst", "signal": "dcf", "text": "x\nSIGNAL_SCORE: 0.50"},
            {"agent_name": "Risk Analyst", "signal": "risk", "text": "y\nSIGNAL_SCORE: 0.50"},
        ],
    }
    return SynthesisCase.model_validate({**base, **overrides})


def test_complete_signal_scores_detected():
    assert _case().has_complete_signal_scores()


def test_missing_signal_score_makes_ground_truth_underivable():
    case = _case(
        agent_reports=[
            {"agent_name": "DCF Analyst", "signal": "dcf", "text": "x\nSIGNAL_SCORE: 0.50"},
            {"agent_name": "Risk Analyst", "signal": "risk", "text": "prose only"},
        ]
    )
    assert not case.has_complete_signal_scores()


# ── cassettes ──────────────────────────────────────────────────────────────


class _StubProvider(LLMProvider):
    name = "stub"
    default_model = "stub-model"

    def __init__(self, response: str = "generated"):
        self.response = response
        self.calls = 0

    async def generate(self, system, user, model=None, max_tokens=4096):
        self.calls += 1
        return self.response


def test_request_key_is_stable_and_prompt_sensitive():
    a = request_key("anthropic", "m", "system", "user")
    assert a == request_key("anthropic", "m", "system", "user")
    assert a != request_key("anthropic", "m", "system EDITED", "user")
    assert a != request_key("anthropic", "m", "system", "user EDITED")
    assert a != request_key("anthropic", "other-model", "system", "user")
    assert a != request_key("openai", "m", "system", "user")


def test_cassette_round_trips(tmp_path):
    path = tmp_path / "suite.json"
    cassette = Cassette(path)
    key = request_key("anthropic", "m", "sys", "usr")
    cassette.put(key, model="m", system="sys", user="usr", response="hello")
    cassette.save()

    reloaded = Cassette(path)
    assert reloaded.get(key) == "hello"
    assert reloaded.get("missing") is None
    assert json.loads(path.read_text())["version"] == CASSETTE_VERSION


def test_cassette_rejects_an_unknown_format_version(tmp_path):
    path = tmp_path / "old.json"
    path.write_text(json.dumps({"version": 99, "records": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="re-record"):
        Cassette(path)


def test_replay_mode_never_calls_the_model(tmp_path):
    cassette = Cassette(tmp_path / "c.json")
    provider = CassetteProvider(cassette, mode="replay")
    with pytest.raises(CassetteMiss, match="python -m evals record"):
        asyncio.run(provider.generate(system="s", user="u"))


def test_replay_mode_returns_the_recording(tmp_path):
    cassette = Cassette(tmp_path / "c.json")
    provider = CassetteProvider(cassette, mode="replay")
    key = request_key(provider.provider_name, provider.default_model, "s", "u")
    cassette.put(key, model=provider.default_model, system="s", user="u", response="cached")

    assert asyncio.run(provider.generate(system="s", user="u")) == "cached"
    assert (provider.hits, provider.misses) == (1, 0)


def test_auto_mode_records_a_miss_then_replays_it(tmp_path):
    cassette = Cassette(tmp_path / "c.json")
    inner = _StubProvider("fresh")
    provider = CassetteProvider(cassette, inner=inner, mode="auto")

    assert asyncio.run(provider.generate(system="s", user="u")) == "fresh"
    assert asyncio.run(provider.generate(system="s", user="u")) == "fresh"
    assert inner.calls == 1, "second call should have been served from the cassette"


def test_record_mode_always_calls_the_model(tmp_path):
    cassette = Cassette(tmp_path / "c.json")
    inner = _StubProvider("fresh")
    provider = CassetteProvider(cassette, inner=inner, mode="record")

    asyncio.run(provider.generate(system="s", user="u"))
    asyncio.run(provider.generate(system="s", user="u"))
    assert inner.calls == 2


def test_recording_modes_require_a_live_provider(tmp_path):
    cassette = Cassette(tmp_path / "c.json")
    with pytest.raises(ValueError, match="live provider"):
        CassetteProvider(cassette, mode="record")


def test_checked_in_cassettes_cover_every_case():
    """Guards against a case landing without its recording, which fails CI late."""
    for suite, cases in (
        ("synthesis", load_synthesis_cases()),
        ("agents", load_agent_cases()),
    ):
        cassette = open_cassette(suite)
        assert len(cassette.records) >= len(cases), (
            f"{suite}: {len(cassette.records)} recordings for {len(cases)} cases"
        )


def test_cassettes_were_recorded_for_the_replay_provider():
    for suite in ("synthesis", "agents"):
        for key, record in open_cassette(suite).records.items():
            assert record["model"] == SEED_MODEL, f"{suite}/{key} recorded off-model"


# ── end-to-end replay ──────────────────────────────────────────────────────


def test_synthesis_suite_runs_clean_offline():
    cases = load_synthesis_cases()
    provider = CassetteProvider(open_cassette("synthesis"), mode="replay")
    config = RunConfig(suite="synthesis", mode="replay", model=SEED_MODEL, concurrency=2)
    report = asyncio.run(run_synthesis_suite(cases, provider, config))

    assert len(report.samples) == len(cases)
    assert report.cassette_misses == 0
    assert report.case_pass_rate == 1.0, report.failures()


def test_agent_suite_runs_clean_offline():
    cases = load_agent_cases()
    provider = CassetteProvider(open_cassette("agents"), mode="replay")
    config = RunConfig(suite="agents", mode="replay", model=SEED_MODEL, concurrency=2)
    report = asyncio.run(run_agent_suite(cases, provider, config))

    assert len(report.samples) == len(cases)
    assert report.cassette_misses == 0
    assert report.case_pass_rate == 1.0, report.failures()


def test_case_filter_selects_a_subset():
    cases = load_synthesis_cases()
    provider = CassetteProvider(open_cassette("synthesis"), mode="replay")
    config = RunConfig(
        suite="synthesis", mode="replay", model=SEED_MODEL, case_filter="adverse_macro"
    )
    report = asyncio.run(run_synthesis_suite(cases, provider, config))
    assert len(report.samples) == 1


def test_a_failing_provider_is_recorded_not_raised():
    class _Broken(LLMProvider):
        name = "broken"
        default_model = SEED_MODEL

        async def generate(self, system, user, model=None, max_tokens=4096):
            raise RuntimeError("upstream 503")

    cases = load_synthesis_cases()[:1]
    config = RunConfig(suite="synthesis", mode="replay", model=SEED_MODEL)
    report = asyncio.run(run_synthesis_suite(cases, _Broken(), config))

    assert report.case_pass_rate == 0.0
    assert "upstream 503" in report.failures()[0][2]


# ── reporting and gating ───────────────────────────────────────────────────


def _sample(case_id: str, *results: CheckResult) -> Sample:
    return Sample(case_id=case_id, output="x", results=list(results))


def _ok(name, severity="error", metric=None):
    return CheckResult(name=name, passed=True, severity=severity, metric=metric)


def _bad(name, severity="error", metric=None):
    return CheckResult(
        name=name, passed=False, detail="broke", severity=severity, metric=metric
    )


def test_case_pass_rate_counts_only_error_failures():
    report = EvalReport(
        suite="s",
        mode="replay",
        model="m",
        samples=[
            _sample("a", _ok("x"), _bad("style", severity="warn")),
            _sample("b", _bad("x")),
        ],
    )
    assert report.case_pass_rate == 0.5


def test_check_stats_aggregate_pass_rate_and_metric():
    report = EvalReport(
        suite="s",
        mode="replay",
        model="m",
        samples=[
            _sample("a", _ok("x", metric=0.1)),
            _sample("b", _bad("x", metric=0.3)),
        ],
    )
    stat = next(s for s in report.check_stats if s.name == "x")
    assert (stat.passed, stat.failed) == (1, 1)
    assert stat.pass_rate == 0.5
    assert stat.mean_metric == pytest.approx(0.2)


def test_gate_blocks_on_case_pass_rate():
    report = EvalReport(
        suite="s", mode="replay", model="m", samples=[_sample("a", _bad("x"))]
    )
    ok, violations = Gate(min_case_pass_rate=1.0).evaluate(report)
    assert not ok
    assert any("case pass rate" in v for v in violations)


def test_gate_allows_a_declared_per_check_tolerance():
    report = EvalReport(
        suite="s",
        mode="replay",
        model="m",
        samples=[_sample("a", _ok("flaky")), _sample("b", _bad("flaky"))],
    )
    gate = Gate(min_case_pass_rate=0.5, min_check_pass_rate={"flaky": 0.5})
    ok, violations = gate.evaluate(report)
    assert ok, violations


def test_gate_ignores_warn_severity_checks():
    report = EvalReport(
        suite="s",
        mode="replay",
        model="m",
        samples=[_sample("a", _bad("style", severity="warn"))],
    )
    ok, violations = Gate().evaluate(report)
    assert ok, violations


def test_baseline_comparison_detects_a_regression():
    report = EvalReport(
        suite="s",
        mode="replay",
        model="m",
        samples=[_sample("a", _ok("x")), _sample("b", _bad("x"))],
    )
    baseline = {"case_pass_rate": 1.0, "checks": [{"name": "x", "pass_rate": 1.0}]}
    regressions = compare_to_baseline(report, baseline)
    assert len(regressions) == 2
    assert any("case pass rate fell" in r for r in regressions)


def test_baseline_comparison_respects_tolerance():
    report = EvalReport(
        suite="s",
        mode="replay",
        model="m",
        samples=[_sample("a", _ok("x")), _sample("b", _bad("x"))],
    )
    baseline = {"case_pass_rate": 0.55, "checks": []}
    assert compare_to_baseline(report, baseline, tolerance=0.1) == []


def test_report_renders_json_and_markdown():
    report = EvalReport(
        suite="s", mode="replay", model="m", samples=[_sample("a", _bad("x"))]
    )
    payload = report.to_dict()
    assert payload["failures"][0]["check"] == "x"
    assert json.dumps(payload)

    markdown = report.to_markdown()
    assert "case pass rate" in markdown
    assert "`x`" in markdown


# ── extraction behaviour the graders rely on ───────────────────────────────


class TestProductionExtractionRobustness:
    """
    ``orchestrator._extract_structured_block`` is the only path by which a
    verdict reaches the API, history table and paper-trading writer, and it
    fails by returning ``None`` rather than raising. These cases pin its
    behaviour on the malformed output shapes that actually occur.
    """

    def _block(self, body: str) -> str:
        return f"Preamble.\n\n```json\n{body}\n```\n\nTrailing prose."

    def test_trailing_comma_is_tolerated(self):
        parsed, _ = extract_structured(self._block('{"verdict": "BUY", "conviction": "HIGH",}'))
        assert parsed == {"verdict": "BUY", "conviction": "HIGH"}

    def test_unfenced_json_is_not_extracted(self):
        parsed, prose = extract_structured('{"verdict": "BUY"}')
        assert parsed is None
        assert prose == '{"verdict": "BUY"}'

    def test_unlabelled_fence_is_extracted(self):
        parsed, _ = extract_structured('Text.\n\n```\n{"verdict": "SELL"}\n```')
        assert parsed == {"verdict": "SELL"}

    def test_first_block_wins_when_several_are_present(self):
        text = (
            '```json\n{"verdict": "BUY"}\n```\n\nAnd an illustrative one:\n\n'
            '```json\n{"verdict": "SELL"}\n```'
        )
        parsed, _ = extract_structured(text)
        assert parsed == {"verdict": "BUY"}, (
            "extraction takes the first fenced block, which is why "
            "check_json_block_first gates on prose preceding the JSON"
        )

    def test_smart_quotes_are_not_recovered(self):
        parsed, _ = extract_structured(self._block('{\u201cverdict\u201d: \u201cBUY\u201d}'))
        assert parsed is None

    def test_truncated_output_yields_no_verdict(self):
        parsed, _ = extract_structured('```json\n{"verdict": "BUY", "health_scores": {')
        assert parsed is None

    def test_a_json_array_is_rejected(self):
        parsed, _ = extract_structured(self._block('[{"verdict": "BUY"}]'))
        assert parsed is None

    def test_prose_survives_extraction(self):
        parsed, prose = extract_structured(self._block('{"verdict": "BUY"}'))
        assert parsed is not None
        assert "Preamble." in prose and "Trailing prose." in prose
        assert "```" not in prose


class TestPatternVectorExtraction:
    def test_picks_the_block_carrying_the_composite(self):
        text = (
            '```json\n{"unrelated": 1}\n```\n\n'
            '```json\n{"composite_score": 0.5, "signal_vector": {}}\n```'
        )
        assert extract_pattern_vector(text)["composite_score"] == 0.5

    def test_returns_none_without_a_vector_block(self):
        assert extract_pattern_vector("no json at all") is None

    def test_tolerates_a_trailing_comma(self):
        text = '```json\n{"composite_score": 0.5,}\n```'
        assert extract_pattern_vector(text) == {"composite_score": 0.5}


# ── seeding ────────────────────────────────────────────────────────────────


def test_seed_provider_constants_match_the_replay_default():
    provider = CassetteProvider(Cassette(fixture_path("nonexistent").parent / "x.json"))
    assert provider.provider_name == SEED_PROVIDER
    assert provider.default_model == SEED_MODEL


def test_load_fixture_returns_none_when_absent():
    assert load_fixture("no-such-case") is None
