"""Direct imports of a wrapped SDK, outside the module that wraps it."""

from __future__ import annotations

from ratchet_gates.types import GateContext, GateName, GateResult, GateStatus


class BannedApiGate:
    """Turns "someone wrote a second S3 client" into something CI refuses.

    Off unless configured, because the wrapper layout is project-specific and
    there is no defensible default. `ratchet-gates learn` fills the table in
    when it finds a wrapper directory. Ruff's TID251 covers the same class
    declaratively for repos that prefer to configure it there.
    """

    name = GateName.BANNED_API

    def run(self, ctx: GateContext) -> GateResult:
        findings: list[str] = []
        checked = 0
        for path in ctx.changed_files:
            if not path.endswith(".py"):
                continue
            banned = ctx.resolve(path).banned_api
            if not banned:
                continue
            if any(path.startswith(wrapper.rstrip("/")) for wrapper in banned.values()):
                continue  # the wrapper itself is where the raw import belongs
            source = ctx.repo / path
            try:
                lines = source.read_text().splitlines()
            except OSError:
                continue
            checked += 1
            for number, text in enumerate(lines, start=1):
                stripped = text.strip()
                for module, wrapper in banned.items():
                    if stripped.startswith(
                        (f"import {module}", f"from {module}")
                    ):
                        findings.append(
                            f"{path}:{number}: imports {module} directly; "
                            f"use {wrapper}"
                        )
        if not checked:
            return GateResult(
                self.name, GateStatus.SKIPPED, "no banned-API table configured"
            )
        return GateResult(
            self.name,
            GateStatus.FAIL if findings else GateStatus.PASS,
            f"{len(findings)} banned import(s)",
            tuple(findings),
        )
