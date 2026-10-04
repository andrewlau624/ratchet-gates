"""Semgrep behind a baseline commit, with per-path rule disabling."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ratchet_gates.git import run
from ratchet_gates.tools import bundled_rules_dir, resolve_tool
from ratchet_gates.types import GateContext, GateName, GateResult, GateStatus


class SemgrepGate:
    """One scan with the union of rule directories, then per-path filtering.

    Scanning once and dropping findings whose path disabled that rule is both
    cheaper and more predictable than one scan per override — semgrep startup
    dominates its runtime on a diff-sized target.
    """

    name = GateName.SEMGREP_BASELINE

    def run(self, ctx: GateContext) -> GateResult:
        policy = ctx.root_profile.semgrep
        if not policy.enabled:
            return GateResult(
                self.name, GateStatus.SKIPPED, "no semgrep rule sources configured"
            )

        semgrep = resolve_tool("semgrep")
        if not semgrep:
            if os.environ.get("GITHUB_ACTIONS") == "true":
                return GateResult(
                    self.name, GateStatus.TOOLING_FAILURE, "semgrep not found"
                )
            return GateResult(
                self.name, GateStatus.SKIPPED, "semgrep not installed locally"
            )

        dirs, failure = self._rule_dirs(ctx, policy.bundled_rules, policy.extra_rule_dirs)
        if failure:
            return failure

        command = [semgrep, "scan"]
        for directory in dirs:
            command += ["--config", str(directory)]
        command += [
            "--baseline-commit",
            ctx.base,
            "--error",
            "--json",
            "--severity",
            policy.severity.value,
        ]
        proc = run(command, ctx.repo)

        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            return GateResult(
                self.name,
                GateStatus.TOOLING_FAILURE,
                f"semgrep output was not JSON (exit {proc.returncode})",
            )

        findings: list[str] = []
        suppressed = 0
        for item in payload.get("results", []):
            path = item.get("path", "")
            check_id = item.get("check_id", "")
            if _is_disabled(check_id, ctx.resolve(path).semgrep.disabled):
                suppressed += 1
                continue
            line = item.get("start", {}).get("line", "?")
            findings.append(f"{path}:{line} {_short(check_id)}")

        detail = f"{len(findings)} new finding(s)"
        if suppressed:
            detail += f" ({suppressed} disabled by an override)"
        return GateResult(
            self.name,
            GateStatus.FAIL if findings else GateStatus.PASS,
            detail,
            tuple(findings),
        )

    def _rule_dirs(
        self, ctx: GateContext, bundled: bool, extra: tuple[str, ...]
    ) -> tuple[list[Path], GateResult | None]:
        dirs: list[Path] = []
        if bundled:
            shipped = bundled_rules_dir()
            if not shipped.is_dir():
                # The rules are not packaged into a wheel. Treating this as an
                # empty rule set would report PASS having scanned nothing.
                return [], GateResult(
                    self.name,
                    GateStatus.TOOLING_FAILURE,
                    f"bundled rules requested but {shipped} is missing — install "
                    f"from a clone, or set semgrep.bundled_rules = false",
                )
            dirs.append(shipped)
        for entry in extra:
            resolved = (ctx.repo / entry).resolve()
            if not resolved.is_dir():
                return [], GateResult(
                    self.name,
                    GateStatus.TOOLING_FAILURE,
                    f"semgrep.extra_rule_dirs: {entry!r} is not a directory",
                )
            dirs.append(resolved)
        return dirs, None


def _short(check_id: str) -> str:
    """semgrep reports a dotted path; the rule's own id is the last segment."""
    return check_id.rsplit(".", 1)[-1] if check_id else check_id


def _is_disabled(check_id: str, disabled: frozenset[str]) -> bool:
    return bool(disabled) and (_short(check_id) in disabled or check_id in disabled)
