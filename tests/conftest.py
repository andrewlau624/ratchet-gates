"""Make the package importable when the tests run from a bare checkout.

Doing this here rather than in each test module is what lets those modules
keep their imports at the top of the file, with no `# noqa: E402` to go stale
when a ruff release changes which codes are on by default.
"""

from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
