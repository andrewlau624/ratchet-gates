"""Conventions a repository writes down in prose.

Everything this inspector produces is SUGGESTED, without exception. Prose
states an intention; it does not establish that a deterministic rule is the
right encoding of it, and the audit behind this tool found conventions that
were written down, configured in a review bot, AND present as a semgrep
target while still recurring on 320 pull requests. Writing a rule because a
document asked for one is how that happens.
"""

from __future__ import annotations

import re
from pathlib import Path

from ratchet_gates.learn.types import Confidence, Signal, SignalKind

DOCS = ("AGENTS.md", "CLAUDE.md", "CONTRIBUTING.md", "CONVENTIONS.md")

#: phrase -> the ruff code that mechanically decides it
CODE_PHRASES: tuple[tuple[str, str], ...] = (
    (r"function[- ]local import|import(s)? (must|should) be at the top", "PLC0415"),
    (r"logger\.exception|logger\.error.*except|except.*logger\.error", "TRY400"),
    (r"\basync\b.*(posture|chain|call site)|don'?t block the event loop", "ASYNC"),
    (r"type:\s*ignore|blanket (type[- ]ignore|noqa)", "PGH003"),
    (r"dangling (asyncio )?task|asyncio\.create_task", "RUF006"),
    (r"modern(ise|ize)d? typing|outdated typing|typing syntax", "UP"),
)

#: phrase -> a real convention that NO deterministic rule decides
JUDGEMENT_PHRASES: tuple[tuple[str, str], ...] = (
    (r"service class", "one owner per domain concept"),
    (r"thin (entrypoint|route|handler)|entrypoints stay thin", "thin entrypoints"),
    (r"control flow", "control-flow legibility"),
    (r"(re)?use existing|don'?t duplicate|single source of truth", "reuse"),
)


class DocsInspector:
    name = "docs"

    def inspect(self, repo: Path) -> list[Signal]:
        out: list[Signal] = []
        for name in DOCS:
            path = repo / name
            if not path.is_file():
                continue
            try:
                lines = path.read_text().splitlines()
            except OSError:
                continue
            for number, line in enumerate(lines, start=1):
                lowered = line.lower()
                for pattern, code in CODE_PHRASES:
                    if re.search(pattern, lowered):
                        out.append(
                            Signal(
                                SignalKind.RUFF_CODE,
                                code,
                                Confidence.SUGGESTED,
                                f'{name}:{number} "{_trim(line)}"',
                            )
                        )
                for pattern, concept in JUDGEMENT_PHRASES:
                    if re.search(pattern, lowered):
                        out.append(
                            Signal(
                                SignalKind.JUDGEMENT,
                                concept,
                                Confidence.SUGGESTED,
                                f'{name}:{number} "{_trim(line)}"',
                            )
                        )
        return out


def _trim(line: str, limit: int = 90) -> str:
    text = line.strip().lstrip("#-*> ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"
