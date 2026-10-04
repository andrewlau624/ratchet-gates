"""Assemble the context once, run every gate, fold one verdict."""

from __future__ import annotations

from pathlib import Path

from ratchet_gates import git
from ratchet_gates.config import ConfigLoader, ResolvedConfig
from ratchet_gates.gates.banned_api import BannedApiGate
from ratchet_gates.gates.base import Gate
from ratchet_gates.gates.free import FreeGate
from ratchet_gates.gates.ruff import RuffGate
from ratchet_gates.gates.semgrep import SemgrepGate
from ratchet_gates.types import (
    GateContext,
    GateResult,
    Verdict,
    verdict_of,
)


class GateService:
    """The one place that knows which gates exist and in what order.

    Everything expensive — finding the base commit, listing changed files,
    parsing the diff for added lines — happens once here and is handed to each
    gate. A gate that wanted any of it on its own would be the second place
    that knows how the ratchet works.
    """

    def __init__(self, repo: Path, config: ResolvedConfig) -> None:
        self.repo = repo
        self.config = config
        self.gates: tuple[Gate, ...] = (
            RuffGate(),
            SemgrepGate(),
            BannedApiGate(),
            FreeGate(),
        )

    @classmethod
    def build(
        cls,
        repo: Path,
        *,
        profile_name: str | None = None,
        ruff_codes: str | None = None,
        semgrep_severity: str | None = None,
    ) -> GateService:
        config = ConfigLoader(repo).load(
            profile_name=profile_name,
            cli_ruff_codes=ruff_codes,
            cli_severity=semgrep_severity,
        )
        return cls(repo, config)

    def run(self, base: str | None = None) -> tuple[list[GateResult], Verdict, str]:
        resolved_base = base or git.find_base_commit(self.repo)
        changed = git.changed_files(self.repo, resolved_base)
        ctx = GateContext(
            repo=self.repo,
            base=resolved_base,
            changed_files=changed,
            root_profile=self.config.root,
            resolve=self.config.for_path,
            added_lines=git.added_lines(self.repo, resolved_base, list(changed)),
        )
        results = [gate.run(ctx) for gate in self.gates]
        return results, verdict_of(results), resolved_base
