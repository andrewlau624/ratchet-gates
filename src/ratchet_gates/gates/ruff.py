"""Ruff, scoped to the lines the diff added."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from pathlib import Path

from ratchet_gates.git import run
from ratchet_gates.tools import resolve_tool
from ratchet_gates.types import (
    Finding,
    GateContext,
    GateName,
    GateResult,
    GateStatus,
)


class RuffGate:
    """Runs the repo's OWN ruff config plus the policy's extra codes.

    `lint.extend-select` rather than `select` is deliberate and load-bearing:
    the repo's established ignores, per-file-ignores and exclusions survive
    intact. Re-enabling a code a team deliberately turned off produces a wall
    of false positives, and a gate that produces one gets routed around.

    Files are grouped by their resolved code set so a monorepo with different
    policies per subtree costs one ruff invocation per distinct set rather
    than one per file.
    """

    name = GateName.RUFF_DIFF

    def run(self, ctx: GateContext) -> GateResult:
        py_files = [f for f in ctx.changed_files if f.endswith(".py")]
        if not py_files:
            return GateResult(
                self.name, GateStatus.SKIPPED, "no python files changed"
            )

        ruff = resolve_tool("ruff")
        if not ruff:
            return GateResult(
                self.name,
                GateStatus.TOOLING_FAILURE,
                "ruff not found on PATH or in the tool's venv",
            )

        groups: dict[tuple[str, ...], list[str]] = defaultdict(list)
        for path in py_files:
            groups[ctx.resolve(path).ruff.codes].append(path)

        findings: list[Finding] = []
        for codes, paths in groups.items():
            if not codes:
                continue  # this subtree deliberately adds nothing
            result = self._check(ruff, ctx, codes, paths)
            if isinstance(result, GateResult):
                return result
            findings.extend(result)

        if not any(groups) or all(not codes for codes in groups):
            return GateResult(
                self.name,
                GateStatus.SKIPPED,
                "no ruff codes enabled for any changed file",
            )
        return GateResult(
            self.name,
            GateStatus.FAIL if findings else GateStatus.PASS,
            f"{len(findings)} new violation(s) on changed lines",
            tuple(findings),
        )

    def _check(
        self,
        ruff: str,
        ctx: GateContext,
        codes: tuple[str, ...],
        paths: list[str],
    ) -> list[Finding] | GateResult:
        env = dict(
            os.environ,
            PATH=":".join([str(Path(ruff).parent), os.environ.get("PATH", "")]),
        )
        selected = ",".join(f'"{c}"' for c in codes)
        proc = run(
            [
                ruff,
                "check",
                "--config",
                f"lint.extend-select=[{selected}]",
                "--output-format",
                "json",
                *paths,
            ],
            ctx.repo,
            env=env,
        )
        if proc.returncode not in (0, 1):
            return GateResult(
                self.name,
                GateStatus.TOOLING_FAILURE,
                f"ruff exited {proc.returncode}: {proc.stderr.strip()[:200]}",
            )
        try:
            reported = json.loads(proc.stdout or "[]")
        except json.JSONDecodeError:
            return GateResult(
                self.name, GateStatus.TOOLING_FAILURE, "ruff output was not JSON"
            )

        out: list[Finding] = []
        for item in reported:
            path = _relative(ctx.repo, item.get("filename", ""))
            row = item.get("location", {}).get("row")
            if row not in ctx.added_lines.get(path, frozenset()):
                continue  # the ratchet: not a line this branch wrote
            out.append(
                Finding(
                    path=path,
                    line=row,
                    code=str(item.get("code") or ""),
                    message=str(item.get("message") or ""),
                )
            )
        return out


def _relative(repo: Path, filename: str) -> str:
    try:
        return str(Path(filename).resolve().relative_to(repo.resolve()))
    except ValueError:
        return filename
