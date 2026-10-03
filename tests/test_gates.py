"""End-to-end tests for ratchet-gates ratchet semantics.

Each test builds an isolated git repo fixture so results depend only on the
tool's own logic, not on the state of any real branch.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

TOOL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL_ROOT / "src"))

from ratchet_gates import cli  # noqa: E402

# Prefer the tool's own venv when present (local runs); in CI the gate
# toolchain is already on PATH, so this resolves to nothing and is skipped.
VENV_BIN = TOOL_ROOT / ".venv" / "bin"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A tiny git repo: base commit on main, then a feature branch.

    Mirrors a real PR: origin/main is the base, HEAD is the feature work.
    """
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@t"], cwd=tmp_path, check=True
    )
    subprocess.run(["git", "config", "user.name", "t"], cwd=tmp_path, check=True)
    (tmp_path / "ok.py").write_text("import os\n\n\ndef f():\n    return os.getcwd()\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=tmp_path, check=True)
    # origin/main is a remote-tracking ref at the base; feature is HEAD.
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=tmp_path, check=True
    )
    subprocess.run(
        ["git", "checkout", "-q", "-b", "feature"], cwd=tmp_path, check=True
    )
    return tmp_path


def _run_cli(repo: Path) -> subprocess.CompletedProcess[str]:
    path = cli.os.environ["PATH"]
    if VENV_BIN.is_dir():
        path = f"{VENV_BIN}:{path}"
    env = dict(cli.os.environ, PATH=path)
    return subprocess.run(
        [sys.executable, "-m", "ratchet_gates", "--repo", str(repo)],
        cwd=TOOL_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )


def test_clean_repo_passes(repo: Path):
    proc = _run_cli(repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "RESULT: CLEAN" in proc.stdout


def test_new_violation_fails(repo: Path):
    (repo / "bad.py").write_text(
        "def f():\n    import json\n    return json.dumps({})\n"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "bad"], cwd=repo, check=True)
    proc = _run_cli(repo)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "PLC0415" in proc.stdout


def test_legacy_violation_does_not_fail(repo: Path):
    """The ratchet: a violation already on origin/main is not the PR's fault."""
    (repo / "bad.py").write_text(
        "def f():\n    import json\n    return json.dumps({})\n"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "legacy"], cwd=repo, check=True)
    # Advance origin/main to include the legacy violation.
    subprocess.run(
        ["git", "update-ref", "refs/remotes/origin/main", "HEAD"], cwd=repo, check=True
    )
    # New clean feature work on top.
    (repo / "new.py").write_text("import os\n\n_ = os.getcwd()\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "new"], cwd=repo, check=True)
    proc = _run_cli(repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_banned_api_fails(repo: Path):
    (repo / "bad.py").write_text(
        "import boto3\n\n\ndef f():\n    return boto3.client('ses')\n"
    )
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "bad"], cwd=repo, check=True)
    proc = _run_cli(repo)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "banned-api" in proc.stdout