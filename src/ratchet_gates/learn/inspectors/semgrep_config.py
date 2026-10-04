"""Semgrep rules the repository already maintains."""

from __future__ import annotations

from pathlib import Path

from ratchet_gates.learn.types import Confidence, Signal, SignalKind
from ratchet_gates.tools import bundled_rules_dir

CANDIDATES = (".semgrep", "semgrep", ".semgrep/rules", "rules/semgrep")


class SemgrepConfigInspector:
    """Point the gate at existing rules rather than duplicating them.

    A repo that already wrote rules has already decided what it cares about.
    Copying them in would create a second copy to drift.
    """

    name = "semgrep_config"

    def inspect(self, repo: Path) -> list[Signal]:
        out: list[Signal] = []
        shipped = bundled_rules_dir().resolve()
        for candidate in CANDIDATES:
            directory = repo / candidate
            if not directory.is_dir():
                continue
            # Never propose a directory that overlaps the rules the gate
            # already loads: semgrep would register every rule twice and
            # report every finding twice.
            resolved = directory.resolve()
            if resolved == shipped or shipped.is_relative_to(resolved):
                continue
            # `targets/` holds the fixtures a rule is tested against, not rules.
            count = len(
                [p for p in directory.rglob("*.y*ml") if "targets" not in p.parts]
            )
            if not count:
                continue
            out.append(
                Signal(
                    SignalKind.SEMGREP_DIR,
                    candidate,
                    Confidence.CERTAIN,
                    f"{count} rule file(s) already maintained here",
                )
            )
        return _drop_nested(repo, out)


def _drop_nested(repo: Path, signals: list[Signal]) -> list[Signal]:
    """Keep the outermost directory of any nested pair.

    semgrep reads a --config directory recursively, so listing both
    `.semgrep` and `.semgrep/rules` registers every rule twice and reports
    every finding twice.
    """
    kept: list[Signal] = []
    for signal in signals:
        path = (repo / signal.key).resolve()
        if any(
            path.is_relative_to((repo / other.key).resolve())
            and path != (repo / other.key).resolve()
            for other in signals
        ):
            continue
        kept.append(signal)
    return kept
