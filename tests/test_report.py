"""Run records and what stacking them up is supposed to tell you."""

from __future__ import annotations

import json
from pathlib import Path

from ratchet_gates.report import (
    ReportService,
    RunReport,
    render_run_markdown,
)
from ratchet_gates.types import Finding, GateName, GateResult, GateStatus, Verdict


def run(verdict: Verdict, *findings: Finding, advisory: bool = False) -> RunReport:
    return RunReport(
        repo="/tmp/x",
        base="abc123def456",
        verdict=verdict,
        advisory=advisory,
        policy=("profile 'default'",),
        gates=(
            GateResult(
                GateName.RUFF_DIFF,
                GateStatus.FAIL if findings else GateStatus.PASS,
                f"{len(findings)} new violation(s)",
                findings,
            ),
        ),
    )


def test_a_record_survives_a_round_trip(tmp_path: Path):
    """The artifact is the only durable trace of a run; it has to reload."""
    original = run(
        Verdict.NEW_VIOLATIONS,
        Finding("a.py", 2, "PLC0415", "import should be at the top-level"),
        advisory=True,
    )
    path = tmp_path / "run.json"
    ReportService().write(original, path)
    restored = RunReport.from_dict(json.loads(path.read_text()))
    assert restored.verdict is Verdict.NEW_VIOLATIONS
    assert restored.advisory is True
    assert restored.findings[0].code == "PLC0415"
    assert restored.findings[0].line == 2


def test_aggregate_counts_runs_not_just_occurrences(tmp_path: Path):
    """Twenty hits in one PR is a refactor; one hit in twenty PRs is a rule."""
    service = ReportService()
    service.write(
        run(Verdict.NEW_VIOLATIONS, *[Finding(f"a{i}.py", i, "TRY400", "x") for i in range(20)]),
        tmp_path / "1.json",
    )
    for i in range(3):
        service.write(
            run(Verdict.NEW_VIOLATIONS, Finding("b.py", 1, "PLC0415", "x")),
            tmp_path / f"spread{i}.json",
        )
    agg = service.aggregate(service.load([tmp_path]), configured=set())
    by_code = {s.code: s for s in agg.stats}
    assert by_code["TRY400"].occurrences == 20 and by_code["TRY400"].runs == 1
    assert by_code["PLC0415"].occurrences == 3 and by_code["PLC0415"].runs == 3
    # Ranked by distinct runs first: breadth beats a single noisy file.
    assert agg.stats[0].code == "PLC0415"


def test_never_fired_treats_a_configured_code_as_a_prefix(tmp_path: Path):
    """`UP` is satisfied by `UP017` firing; comparing sets calls it dead."""
    service = ReportService()
    service.write(
        run(Verdict.NEW_VIOLATIONS, Finding("a.py", 1, "UP017", "x")),
        tmp_path / "1.json",
    )
    agg = service.aggregate(
        service.load([tmp_path]), configured={"UP", "TRY400", "PLC0415"}
    )
    assert "UP" not in agg.never_fired
    assert set(agg.never_fired) == {"TRY400", "PLC0415"}


def test_advisory_runs_are_counted_as_would_have_blocked(tmp_path: Path):
    """The whole point of an advisory period is this number."""
    service = ReportService()
    service.write(run(Verdict.CLEAN), tmp_path / "1.json")
    service.write(
        run(Verdict.NEW_VIOLATIONS, Finding("a.py", 1, "X", "x"), advisory=True),
        tmp_path / "2.json",
    )
    agg = service.aggregate(service.load([tmp_path]), configured=set())
    assert (agg.runs, agg.clean, agg.would_have_blocked, agg.advisory_runs) == (2, 1, 1, 1)


def test_markdown_says_plainly_that_advisory_is_not_blocking():
    body = render_run_markdown(
        run(Verdict.NEW_VIOLATIONS, Finding("a.py", 1, "X", "boom"), advisory=True)
    )
    assert "advisory: not blocking this merge" in body
    assert "`a.py:1`" in body
    assert "boom" in body
