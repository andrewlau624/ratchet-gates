"""The ratchet: which commit to measure against, and which lines are new.

This module is the whole differentiator in about eighty lines. Everything else
in the tool is a linter wrapper; this is the part that makes a linter adoptable
in a repository that already has ten thousand violations.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def run(
    cmd: list[str],
    cwd: Path,
    *,
    check: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, cwd=cwd, text=True, capture_output=True, check=check, env=env
    )


def _git(cwd: Path, *args: str) -> str:
    return run(["git", *args], cwd, check=True).stdout.strip()


def _git_ok(cwd: Path, *args: str) -> bool:
    try:
        run(["git", *args], cwd, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def find_base_commit(cwd: Path) -> str:
    """The merge-base against the default branch, or HEAD if none exists.

    The baseline is a COMMIT, never a checked-in file. A file baseline can be
    edited by the pull request it is supposed to constrain; a merge-base
    cannot.
    """
    candidates: list[str] = []
    try:
        default = _git(cwd, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        if default:
            candidates.append(default)
    except subprocess.CalledProcessError:
        pass
    for branch in ("origin/main", "origin/master", "main", "master"):
        if branch not in candidates:
            candidates.append(branch)
    for branch in candidates:
        if not _git_ok(cwd, "rev-parse", "--verify", branch):
            continue
        try:
            return _git(cwd, "merge-base", branch, "HEAD")
        except subprocess.CalledProcessError:
            continue
    # No default-branch ref at all: diff against the previous commit so the
    # tool still does something useful in a fresh repository.
    try:
        return _git(cwd, "rev-parse", "HEAD~1")
    except subprocess.CalledProcessError:
        return _git(cwd, "rev-parse", "HEAD")


def changed_files(cwd: Path, base: str) -> tuple[str, ...]:
    out = run(
        ["git", "diff", "--name-only", "--diff-filter=ACM", f"{base}...HEAD"],
        cwd,
        check=True,
    )
    return tuple(ln for ln in out.stdout.splitlines() if ln.strip())


def added_lines(cwd: Path, base: str, files: list[str]) -> dict[str, frozenset[int]]:
    """Line numbers the diff ADDED, keyed by file.

    Keyed by file deliberately. The previous implementation merged every file's
    line numbers into one set and then filtered findings by row alone, so a
    finding on line 12 of an untouched file counted as new whenever any file in
    the diff had added a line 12.
    """
    if not files:
        return {}
    proc = run(
        ["git", "diff", "--unified=0", f"{base}...HEAD", "--", *files], cwd
    )
    per_file: dict[str, set[int]] = {}
    current: str | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("+++ b/"):
            current = line[len("+++ b/") :]
            per_file.setdefault(current, set())
        elif line.startswith("+++ /dev/null"):
            current = None
        elif line.startswith("@@") and current is not None:
            match = HUNK_HEADER.match(line)
            if not match:
                continue
            start = int(match.group(1))
            count = int(match.group(2) or 1)
            per_file[current].update(range(start, start + count))
    return {path: frozenset(lines) for path, lines in per_file.items()}
