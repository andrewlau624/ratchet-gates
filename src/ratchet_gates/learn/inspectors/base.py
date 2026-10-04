from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ratchet_gates.learn.types import Signal


class Inspector(Protocol):
    name: str

    def inspect(self, repo: Path) -> list[Signal]: ...
