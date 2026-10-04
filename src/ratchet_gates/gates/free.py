"""Cheap checks that need no external tool."""

from __future__ import annotations

from ratchet_gates.git import run
from ratchet_gates.types import (
    Finding,
    GateContext,
    GateName,
    GateResult,
    GateStatus,
)


class FreeGate:
    """`:latest` image tags (per file) and alembic single-head (per repo).

    The alembic check reads the ROOT policy, never an override: a migration
    graph is a property of the repository and there is no single path to
    attribute it to. The config loader rejects the key inside an override
    rather than accepting and ignoring it.
    """

    name = GateName.FREE_GATES

    def run(self, ctx: GateContext) -> GateResult:
        findings: list[Finding] = []
        ran_any = False

        for path in ctx.changed_files:
            if not path.endswith((".yml", ".yaml")):
                continue
            if not ctx.resolve(path).free_gates.latest_image_tag:
                continue
            ran_any = True
            try:
                text = (ctx.repo / path).read_text()
            except OSError:
                continue
            for number, line in enumerate(text.splitlines(), start=1):
                if "image:" in line and ":latest" in line:
                    findings.append(
                        Finding(
                            path=path,
                            line=number,
                            code="latest-image-tag",
                            message="container image pinned to :latest",
                        )
                    )

        if ctx.root_profile.free_gates.alembic_single_head:
            alembic = ctx.repo / "alembic"
            if alembic.is_dir():
                ran_any = True
                heads = run(["python3", "-m", "alembic", "heads"], ctx.repo)
                if heads.returncode == 0:
                    count = len(
                        [ln for ln in heads.stdout.splitlines() if ln.strip()]
                    )
                    if count > 1:
                        findings.append(
                            Finding(
                                path="alembic",
                                line=None,
                                code="alembic-multi-head",
                                message=f"{count} migration heads (must be 1)",
                            )
                        )

        if not ran_any:
            return GateResult(
                self.name, GateStatus.SKIPPED, "nothing in scope for the free gates"
            )
        return GateResult(
            self.name,
            GateStatus.FAIL if findings else GateStatus.PASS,
            f"{len(findings)} finding(s)",
            tuple(findings),
        )
