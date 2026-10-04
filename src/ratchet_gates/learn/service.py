"""Derive a profile from a repository.

`learn` runs every inspector, collects their `Signal`s, and hands the set to
the renderer. It deliberately does not reconcile them into a single opinion in
code: the renderer groups by confidence so that a reader sees what was read,
what was inferred, and what evidence stands behind each — which is the only
way the output is reviewable rather than magic.

One rule outranks everything: a code the repository explicitly ignores is
never enabled, whatever else suggests it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ratchet_gates.learn.inspectors.base import Inspector
from ratchet_gates.learn.inspectors.docs import DocsInspector
from ratchet_gates.learn.inspectors.history import HistoryInspector
from ratchet_gates.learn.inspectors.layout import LayoutInspector
from ratchet_gates.learn.inspectors.ruff_config import RuffConfigInspector
from ratchet_gates.learn.inspectors.semgrep_config import SemgrepConfigInspector
from ratchet_gates.learn.types import Confidence, Signal, SignalKind


@dataclass(frozen=True)
class LearnResult:
    repo_name: str
    generated_on: str
    signals: tuple[Signal, ...]
    history_attempted: bool = False

    def of(self, kind: SignalKind, confidence: Confidence | None = None) -> list[Signal]:
        return [
            s
            for s in self.signals
            if s.kind is kind and (confidence is None or s.confidence is confidence)
        ]

    @property
    def blocked_codes(self) -> set[str]:
        return {s.key for s in self.of(SignalKind.RUFF_CODE_BLOCKED)}


class LearnService:
    """Runs the inspectors. One hop from the CLI, one hop to each inspector."""

    def __init__(self, inspectors: tuple[Inspector, ...] | None = None) -> None:
        self.inspectors = inspectors or (
            RuffConfigInspector(),
            LayoutInspector(),
            SemgrepConfigInspector(),
            DocsInspector(),
        )

    def learn(self, repo: Path, *, from_history: bool = False) -> LearnResult:
        signals: list[Signal] = []
        for inspector in self.inspectors:
            signals.extend(inspector.inspect(repo))
        if from_history:
            signals.extend(HistoryInspector().inspect(repo))
        return LearnResult(
            repo_name=repo.resolve().name,
            generated_on=datetime.now(tz=UTC).date().isoformat(),
            signals=tuple(signals),
            history_attempted=from_history,
        )
