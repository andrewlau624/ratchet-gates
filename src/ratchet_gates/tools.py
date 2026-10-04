"""Locating the external binaries the gates shell out to.

Resolution order is PATH, then the tool's own virtualenv. The second rung
exists so a clone-and-`make install` checkout works without the caller having
activated anything; it is why there are no absolute paths anywhere in this
repository.
"""

from __future__ import annotations

import shutil
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
#: The checkout root when running from a clone (src/ratchet_gates -> ..).
REPO_ROOT = PACKAGE_ROOT.parents[1]


def resolve_tool(binary: str) -> str | None:
    found = shutil.which(binary)
    if found:
        return found
    own = REPO_ROOT / ".venv" / "bin" / binary
    return str(own) if own.exists() else None


def bundled_rules_dir() -> Path:
    """Where the shipped semgrep rules live in a source checkout.

    Not present in a wheel install — the caller must treat a missing directory
    as a tooling failure rather than an empty rule set. See issue #1.
    """
    return REPO_ROOT / "rules" / "semgrep" / "rules"
