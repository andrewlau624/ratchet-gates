"""Render a LearnResult as a reviewable .ratchet-gates.toml.

Every enabled setting carries the evidence that justified it, and everything
inferred rather than read is emitted commented out. A config you cannot audit
line by line is a config nobody audits, and an unaudited rule set is how a
gate accumulates false positives until somebody turns it off.
"""

from __future__ import annotations

import textwrap
from collections import defaultdict

from ratchet_gates.learn.service import LearnResult
from ratchet_gates.learn.types import Confidence, SignalKind

WIDTH = 74


def _wrap(text: str) -> list[str]:
    return textwrap.wrap(text, width=WIDTH) or [""]


def render_toml(result: LearnResult) -> str:
    out: list[str] = []
    out += _header(result)
    out += _ruff(result)
    out += _semgrep(result)
    out += _banned_api(result)
    out += _free_gates(result)
    out += _overrides(result)
    out += _judgement(result)
    return "\n".join(out).rstrip() + "\n"


def _header(result: LearnResult) -> list[str]:
    lines = [
        (
            f"# ratchet-gates profile learned from {result.repo_name} "
            f"on {result.generated_on}."
        ),
        "#",
        "# Read this before committing it. Every enabled setting below was READ",
        "# from a config file or from the directory layout. Everything commented",
        "# out was INFERRED, and carries the evidence that suggested it — turning",
        "# one on is your decision, not this tool's.",
    ]
    if not result.history_attempted:
        lines += [
            "#",
            "# Static inspection only. `learn --from-history` additionally mines",
            "# this repo's merged pull requests for conventions reviewers enforce",
            "# in practice, which is usually a different set from the written one.",
        ]
    return lines + [""]


def _ruff(result: LearnResult) -> list[str]:
    blocked = result.blocked_codes
    certain = result.of(SignalKind.RUFF_CODE, Confidence.CERTAIN)
    enabled = [s for s in certain if s.key not in blocked]

    lines = ["[ruff]"]
    for signal in result.of(SignalKind.RUFF_CODE_BLOCKED):
        lines.append(f"# {signal.key} — {signal.evidence}")
    # Collapse identical evidence: nine copies of the same sentence is noise,
    # and noise is what stops a generated file from being read.
    shared = {s.evidence for s in enabled}
    if len(shared) == 1 and len(enabled) > 1:
        lines.append(f"# all codes below — {enabled[0].evidence}")
    else:
        for signal in enabled:
            lines.append(f"# {signal.key} — {signal.evidence}")
    if enabled:
        rendered = ", ".join(f'"{s.key}"' for s in enabled)
        lines.append(f"codes = [{rendered}]")
    else:
        lines.append("codes = []")

    suggested: dict[str, list[str]] = defaultdict(list)
    for signal in result.of(SignalKind.RUFF_CODE, Confidence.SUGGESTED):
        if signal.key in blocked or any(s.key == signal.key for s in enabled):
            continue
        suggested[signal.key].append(signal.evidence)
    if suggested:
        lines += [
            "#",
            "# Suggested, NOT enabled. The evidence is prose, which states an",
            "# intention without establishing that this code is the right way to",
            "# enforce it. Add the code above only if you agree it is.",
        ]
        for code, evidence in sorted(suggested.items()):
            lines.append(f"#   {code}")
            for item in evidence[:3]:
                lines.append(f"#     {item}")
    return lines + [""]


def _semgrep(result: LearnResult) -> list[str]:
    dirs = result.of(SignalKind.SEMGREP_DIR)
    lines = ["[semgrep]", 'severity = "ERROR"', "bundled_rules = true"]
    for signal in dirs:
        lines.append(f"# {signal.key} — {signal.evidence}")
    rendered = ", ".join(f'"{s.key}"' for s in dirs)
    lines.append(f"extra_rule_dirs = [{rendered}]")
    lines.append("disabled = []")
    return lines + [""]


def _banned_api(result: LearnResult) -> list[str]:
    certain = result.of(SignalKind.BANNED_API, Confidence.CERTAIN)
    suggested = result.of(SignalKind.BANNED_API, Confidence.SUGGESTED)
    lines = ["[banned_api]"]
    if not certain and not suggested:
        lines += [
            "# No wrapper directory found, so this gate stays off. If this repo",
            "# does centralise its clients somewhere, add",
            '# `module = "path/to/wrapper.py"` pairs here and CI will refuse a',
            "# second one.",
        ]
        return lines + [""]

    seen: set[str] = set()
    for signal in certain:
        if signal.key in seen:
            continue
        seen.add(signal.key)
        lines.append(f"# {signal.key} — {signal.evidence}")
        lines.append(f'{signal.key} = "{signal.value}"')

    pending = [s for s in suggested if s.key not in seen]
    if pending:
        lines += [
            "#",
            "# Suggested, NOT enabled. Banning an import across the repository",
            "# on a wrong guess about which module is the wrapper produces a",
            "# wall of false positives on day one. Confirm the wrapper, then",
            "# uncomment.",
        ]
        for signal in pending:
            lines += [f"#   {chunk}" for chunk in _wrap(f"{signal.key} — {signal.evidence}")]
            lines.append(f'#   {signal.key} = "{signal.value}"')
    return lines + [""]


def _free_gates(result: LearnResult) -> list[str]:
    lines = ["[free_gates]"]
    for signal in result.of(SignalKind.FREE_GATE):
        lines.append(f"# {signal.key} — {signal.evidence}")
        lines.append(f"{signal.key} = {signal.value}")
    return lines + [""]


def _overrides(result: LearnResult) -> list[str]:
    paths = result.of(SignalKind.OVERRIDE_PATHS)
    if not paths:
        return []
    lines = [
        "# Override blocks refine the policy for a subtree. All matching blocks",
        "# apply in declaration order; later blocks win. These are commented out:",
        "# relaxing a rule somewhere is a decision, and the audit found test",
        "# directories are exactly where violations relocate to when you do.",
    ]
    for signal in paths:
        lines += [f"#   {chunk}" for chunk in _wrap(signal.evidence)]
        lines.append("# [[override]]")
        lines.append(f'# paths = ["{signal.key}"]')
        if signal.value:
            codes = ", ".join(f'"{c}"' for c in signal.value.split(",") if c)
            lines.append(f"# ruff = {{ remove = [{codes}] }}")
        lines.append("#")
    return lines + [""]


def _judgement(result: LearnResult) -> list[str]:
    items = result.of(SignalKind.JUDGEMENT)
    if not items:
        return []
    grouped: dict[str, list[str]] = defaultdict(list)
    for signal in items:
        grouped[signal.key].append(signal.evidence)
    lines = [
        "# ---------------------------------------------------------------------",
        "# Conventions found in this repo that NO deterministic rule decides.",
        "# These are not config. They belong to the reviewer, and",
        "# rules/reviewer-prompt.md is the contract for them.",
    ]
    for concept, evidence in sorted(grouped.items()):
        lines.append(f"#   {concept}")
        for item in evidence[:2]:
            lines.append(f"#     {item}")
    return lines
