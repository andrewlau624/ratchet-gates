"""What every gate is.

A gate is handed a fully resolved context and returns one `GateResult`. It
does not read the environment, open a config file, or decide the run's exit
code — `ConfigLoader` answered the first two before it was constructed and
`GateService` folds the third afterwards.
"""

from __future__ import annotations

from typing import Protocol

from ratchet_gates.types import GateContext, GateName, GateResult


class Gate(Protocol):
    name: GateName

    def run(self, ctx: GateContext) -> GateResult: ...
