"""Run records, and what you learn by stacking them up.

A single gate run answers "is this pull request clean". That is enough to
block on and not nearly enough to decide WHAT to block on. The question that
matters during adoption — which rules actually fire here, how often, and
which have never fired at all — is only answerable across many runs, so each
run writes a machine-readable record and `ratchet-gates report` folds them.

The never-fired list is the important half. A rule that has not matched in
two hundred pull requests is not protecting anything; it is latency and a
future false positive. Google's published operating number for disabling an
analyzer is a 10% effective false-positive rate, and you cannot compute that
without counting.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from ratchet_gates.types import Finding, GateResult, GateStatus, Verdict

SCHEMA = "ratchet-gates/run/1"


def _tool_version() -> str:
    try:
        return version("ratchet-gates")
    except PackageNotFoundError:
        return "unknown"


@dataclass(frozen=True)
class RunReport:
    repo: str
    base: str
    verdict: Verdict
    advisory: bool
    policy: tuple[str, ...]
    gates: tuple[GateResult, ...]
    context: dict[str, str] = field(default_factory=dict)
    tool_version: str = field(default_factory=_tool_version)

    @property
    def findings(self) -> list[Finding]:
        return [f for gate in self.gates for f in gate.findings]

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "tool_version": self.tool_version,
            "repo": self.repo,
            "base": self.base,
            "verdict": self.verdict.value,
            "advisory": self.advisory,
            "policy": list(self.policy),
            "context": self.context,
            "gates": [g.as_dict() for g in self.gates],
        }

    @classmethod
    def from_dict(cls, raw: dict) -> RunReport:
        if raw.get("schema") != SCHEMA:
            raise ValueError(f"unrecognised report schema {raw.get('schema')!r}")
        gates = tuple(
            GateResult(
                name=g["gate"],
                status=GateStatus(g["status"]),
                detail=g.get("detail", ""),
                findings=tuple(
                    Finding(
                        path=f["path"],
                        line=f.get("line"),
                        code=f.get("code", ""),
                        message=f.get("message", ""),
                    )
                    for f in g.get("findings", [])
                ),
            )
            for g in raw.get("gates", [])
        )
        return cls(
            repo=raw.get("repo", ""),
            base=raw.get("base", ""),
            verdict=Verdict(raw["verdict"]),
            advisory=bool(raw.get("advisory")),
            policy=tuple(raw.get("policy", [])),
            gates=gates,
            context=dict(raw.get("context", {})),
            tool_version=raw.get("tool_version", "unknown"),
        )


@dataclass(frozen=True)
class CodeStat:
    code: str
    occurrences: int
    runs: int
    examples: tuple[str, ...]


@dataclass(frozen=True)
class Aggregate:
    runs: int
    advisory_runs: int
    would_have_blocked: int
    clean: int
    tooling_failures: int
    stats: tuple[CodeStat, ...]
    never_fired: tuple[str, ...]


class ReportService:
    """Writes one run, and folds many."""

    def write(self, report: RunReport, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report.as_dict(), indent=2) + "\n")

    def load(self, paths: list[Path]) -> list[RunReport]:
        reports: list[RunReport] = []
        for path in sorted(self._expand(paths)):
            try:
                reports.append(RunReport.from_dict(json.loads(path.read_text())))
            except (OSError, ValueError, KeyError) as exc:
                print(f"skipping {path}: {exc}")
        return reports

    def _expand(self, paths: list[Path]) -> list[Path]:
        out: list[Path] = []
        for path in paths:
            if path.is_dir():
                out.extend(path.rglob("*.json"))
            elif path.is_file():
                out.append(path)
        return out

    def aggregate(self, reports: list[RunReport], configured: set[str]) -> Aggregate:
        occurrences: dict[str, int] = defaultdict(int)
        runs_with: dict[str, set[int]] = defaultdict(set)
        examples: dict[str, list[str]] = defaultdict(list)

        for index, report in enumerate(reports):
            for finding in report.findings:
                occurrences[finding.code] += 1
                runs_with[finding.code].add(index)
                if len(examples[finding.code]) < 3:
                    examples[finding.code].append(finding.render())

        stats = tuple(
            CodeStat(
                code=code,
                occurrences=count,
                runs=len(runs_with[code]),
                examples=tuple(examples[code]),
            )
            for code, count in sorted(
                occurrences.items(), key=lambda kv: (-len(runs_with[kv[0]]), -kv[1])
            )
        )
        return Aggregate(
            runs=len(reports),
            advisory_runs=sum(1 for r in reports if r.advisory),
            would_have_blocked=sum(
                1 for r in reports if r.verdict is Verdict.NEW_VIOLATIONS
            ),
            clean=sum(1 for r in reports if r.verdict is Verdict.CLEAN),
            tooling_failures=sum(
                1 for r in reports if r.verdict is Verdict.TOOLING_FAILURE
            ),
            stats=stats,
            never_fired=tuple(sorted(_never_fired(configured, set(occurrences)))),
        )


def _never_fired(configured: set[str], observed: set[str]) -> set[str]:
    """A configured code is a PREFIX: `UP` is satisfied by `UP017` firing.

    Comparing the two sets directly reports whole rule families as dead while
    their subcodes are the loudest thing in the report.
    """
    return {
        code
        for code in configured
        if not any(seen.startswith(code) for seen in observed)
    }


VERDICT_BADGE = {
    Verdict.CLEAN: "✅ clean",
    Verdict.NEW_VIOLATIONS: "❌ new violations",
    Verdict.TOOLING_FAILURE: "⚠️ tooling failure",
}


def render_run_markdown(report: RunReport) -> str:
    """One run, for a job summary or a pull-request comment."""
    lines = [
        "### ratchet-gates",
        "",
        f"**{VERDICT_BADGE[report.verdict]}**"
        + ("  ·  _advisory: not blocking this merge_" if report.advisory else ""),
        "",
        f"<sub>policy: `{' -> '.join(report.policy)}` · base: `{report.base[:12]}`</sub>",
        "",
        "| | gate | result |",
        "|---|---|---|",
    ]
    icon = {
        GateStatus.PASS: "✅",
        GateStatus.FAIL: "❌",
        GateStatus.SKIPPED: "⏭️",
        GateStatus.TOOLING_FAILURE: "⚠️",
    }
    for gate in report.gates:
        name = gate.name.value if hasattr(gate.name, "value") else gate.name
        lines.append(f"| {icon[gate.status]} | `{name}` | {gate.detail} |")

    findings = report.findings
    if findings:
        lines += [
            "",
            (
                f"<details open><summary><b>{len(findings)} finding(s)</b> — "
                "only on lines this branch added</summary>"
            ),
            "",
            "| file | code | detail |",
            "|---|---|---|",
        ]
        for finding in findings[:50]:
            where = (
                f"`{finding.path}:{finding.line}`"
                if finding.line is not None
                else f"`{finding.path}`"
            )
            lines.append(f"| {where} | `{finding.code}` | {finding.message} |")
        if len(findings) > 50:
            lines.append(f"| … | | and {len(findings) - 50} more |")
        lines += ["", "</details>"]
    return "\n".join(lines) + "\n"


def render_aggregate(agg: Aggregate, *, markdown: bool = False) -> str:
    bullet = "- " if markdown else "  "
    lines = [
        "### ratchet-gates — across runs" if markdown else "ratchet-gates — across runs",
        "",
        f"{bullet}runs: {agg.runs} ({agg.advisory_runs} advisory)",
        f"{bullet}would have blocked: {agg.would_have_blocked}",
        f"{bullet}clean: {agg.clean}",
        f"{bullet}tooling failures: {agg.tooling_failures}",
        "",
    ]
    if agg.stats:
        lines.append("**What fires**" if markdown else "What fires")
        lines.append("")
        if markdown:
            lines += ["| code | runs | total | example |", "|---|---:|---:|---|"]
            for stat in agg.stats:
                example = stat.examples[0] if stat.examples else ""
                lines.append(
                    f"| `{stat.code}` | {stat.runs} | {stat.occurrences} | `{example}` |"
                )
        else:
            for stat in agg.stats:
                lines.append(
                    f"  {stat.code:38} {stat.runs:>4} runs  {stat.occurrences:>5} total"
                )
                for example in stat.examples[:1]:
                    lines.append(f"      e.g. {example}")
        lines.append("")
    if agg.never_fired:
        lines += [
            "**Never fired**" if markdown else "Never fired",
            "",
            (
                "These are configured and have matched nothing. A rule that has"
                " not fired is not protecting anything — it is latency and a"
                " future false positive. Drop it or prove it with a fixture."
            ),
            "",
        ]
        lines += [f"{bullet}`{code}`" if markdown else f"  {code}" for code in agg.never_fired]
        lines.append("")
    return "\n".join(lines)
