"""The tool's own gate suite.

A rule that silently stops matching reports PASS forever, which is
indistinguishable from compliance. Both suites below are the tripwire for
that, and `make self-check` is the only claim this project makes about itself.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from ratchet_gates.git import run
from ratchet_gates.tools import REPO_ROOT, bundled_rules_dir, resolve_tool


def self_check() -> int:
    failures = 0

    python = REPO_ROOT / ".venv" / "bin" / "python"
    interpreter = str(python) if python.exists() else sys.executable
    ruff = resolve_tool("ruff")
    env = dict(
        os.environ,
        PYTHONPATH=str(REPO_ROOT / "src"),
        PATH=":".join(
            [str(Path(ruff).parent) if ruff else "", os.environ.get("PATH", "")]
        ),
    )
    pytest_run = run(
        [interpreter, "-m", "pytest", "-q", str(REPO_ROOT / "tests")],
        cwd=REPO_ROOT,
        env=env,
    )
    print(f"[{'PASS' if pytest_run.returncode == 0 else 'FAIL'}] pytest gate suite")
    if pytest_run.returncode != 0:
        print(pytest_run.stdout[-3000:])
        print(pytest_run.stderr[-2000:])
        failures += 1

    semgrep = resolve_tool("semgrep") or str(REPO_ROOT / ".venv" / "bin" / "semgrep")
    fixtures = run(
        [
            semgrep,
            "--test",
            "--config",
            str(bundled_rules_dir()),
            str(REPO_ROOT / "rules" / "semgrep" / "targets"),
        ],
        cwd=REPO_ROOT,
    )
    print(f"[{'PASS' if fixtures.returncode == 0 else 'FAIL'}] semgrep rule fixtures")
    if fixtures.returncode != 0:
        print(fixtures.stdout[-3000:])
        print(fixtures.stderr[-2000:])
        failures += 1

    return 0 if failures == 0 else 1
