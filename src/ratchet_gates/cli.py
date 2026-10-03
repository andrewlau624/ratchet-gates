"""ratchet-gates — ratcheted deterministic enforcement gates.

Every gate fails only on *new* violations relative to the merge-base commit,
so legacy findings never block adoption and no suppressions sweep is needed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str = ""
    findings: list[str] = field(default_factory=list)


def _run(
    cmd: list[str],
    cwd: Path,
    *,
    check: bool = False,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=check,
        env=env,
    )


def _git(cwd: Path, *args: str) -> str:
    """Run git, return stdout stripped. Raises on failure."""
    out = _run(["git", *args], cwd, check=True)
    return out.stdout.strip()


def _git_ok(cwd: Path, *args: str) -> bool:
    try:
        _run(["git", *args], cwd, check=True)
        return True
    except subprocess.CalledProcessError:
        return False


def find_base_commit(cwd: Path) -> str:
    """The merge-base against the default branch, or HEAD if none exists."""
    candidates = []
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
    # No default branch remote and no local main/master: diff against the
    # previous commit so the tool still works on a fresh repo.
    try:
        return _git(cwd, "rev-parse", "HEAD~1")
    except subprocess.CalledProcessError:
        return _git(cwd, "rev-parse", "HEAD")


def changed_files(cwd: Path, base: str) -> list[str]:
    out = _run(
        ["git", "diff", "--name-only", "--diff-filter=ACM", f"{base}...HEAD"],
        cwd,
        check=True,
    )
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def _tool(binary: str) -> str | None:
    """Resolve a binary on PATH or in this tool's own venv (portable)."""
    found = shutil.which(binary)
    if found:
        return found
    own = REPO_ROOT / ".venv" / "bin" / binary
    if own.exists():
        return str(own)
    return None


def ruff_gate(cwd: Path, base: str, files: list[str]) -> GateResult:
    """Ruff scoped to changed lines only.

    Uses the repo's NATIVE ruff config plus our rules via `extend-select`, so
    the repo's established baseline (ignores, per-file-ignores, exclusions)
    is fully preserved. This matters: re-enabling a code the repo already
    explicitly ignores (e.g. E501) produces a wall of false positives that
    gets the gate bypassed. New rules are added, nothing is revoked.

    Findings are filtered to lines ADDED by the diff (the ratchet): legacy
    violations elsewhere never count, so adoption needs no cleanup.
    """
    ruff = _tool("ruff")
    if not ruff:
        return GateResult("ruff-diff", False, "ruff not found")
    py_files = [f for f in files if f.endswith(".py")]
    if not py_files:
        return GateResult("ruff-diff", True, "no python files changed")
    tool_dirs = {str(Path(ruff).parent)}
    env = dict(
        os.environ,
        PATH=":".join([*tool_dirs, os.environ.get("PATH", "")]),
    )
    extra = os.environ.get(
        "RATCHET_GATES_RUFF_CODES",
        "PLC0415,TRY400,UP,TID251,ASYNC,RUF006,RUF100,PGH003,PGH004",
    )
    quoted = ",".join(f'"{c.strip()}"' for c in extra.split(",") if c.strip())
    proc = _run(
        [
            ruff,
            "check",
            "--config",
            f"lint.extend-select=[{quoted}]",
            "--output-format",
            "json",
            *py_files,
        ],
        cwd,
        env=env,
    )
    if proc.returncode not in (0, 1):
        return GateResult(
            "ruff-diff", False, f"ruff crashed (exit {proc.returncode})"
        )
    try:
        findings = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return GateResult("ruff-diff", False, "ruff output not JSON")

    added_lines = _added_lines(cwd, base, py_files)
    on_changed_lines = [
        f for f in findings if f.get("location", {}).get("row") in added_lines
    ]
    return GateResult(
        "ruff-diff",
        passed=not on_changed_lines,
        detail=f"{len(on_changed_lines)} new violation(s) on changed lines",
        findings=[
            f"{f.get('filename')}:{f.get('location', {}).get('row')} {f.get('code')} {f.get('message')}"
            for f in on_changed_lines
        ],
    )


def _added_lines(cwd: Path, base: str, files: list[str]) -> set[int]:
    """Set of line numbers ADDED by the diff, per-file merged.

    Diff scoping is the ratchet: only lines introduced by the PR count.
    """
    added: set[int] = set()
    proc = _run(
        [
            "git",
            "diff",
            "--unified=0",
            f"{base}...HEAD",
            "--",
            *files,
        ],
        cwd,
        check=False,
    )
    cur_file: str | None = None
    for ln in proc.stdout.splitlines():
        if ln.startswith("+++ b/"):
            cur_file = ln[6:]
        elif ln.startswith("@@"):
            # @@ -a,b +c,d @@
            m = re.search(r"\+(\d+)(?:,(\d+))?", ln)
            if m and cur_file:
                start = int(m.group(1))
                count = int(m.group(2) or 1)
                if count > 0:
                    for n in range(start, start + count):
                        added.add(n)
    return added


def semgrep_gate(cwd: Path, base: str, severity: str = "ERROR") -> GateResult:
    """Semgrep with a baseline: only NEW findings fail the gate."""
    semgrep = _tool("semgrep")
    if not semgrep:
        in_ci = os.environ.get("GITHUB_ACTIONS") == "true"
        if in_ci:
            return GateResult("semgrep-baseline", False, "semgrep not found")
        return GateResult(
            "semgrep-baseline", True, "SKIPPED: semgrep not installed locally"
        )
    # rules/semgrep/rules/ specifically, NOT its parent. The parent also holds
    # the consolidated bundle (bundle.yml), so pointing semgrep at it loads
    # every rule twice and double-counts every finding. This directory is also
    # exactly what `--self-check` runs `semgrep --test` against, so the rules
    # the gate enforces are the rules the fixtures govern.
    rules_dir = REPO_ROOT / "rules" / "semgrep" / "rules"
    if not rules_dir.exists():
        return GateResult("semgrep-baseline", True, "no bundled semgrep rules")
    proc = _run(
        [
            semgrep,
            "scan",
            "--config",
            str(rules_dir),
            "--baseline-commit",
            base,
            "--error",
            "--json",
            "--severity",
            severity,
        ],
        cwd,
    )
    findings = []
    try:
        data = json.loads(proc.stdout or "{}")
        for r in data.get("results", []):
            loc = r.get("path", "") + ":" + str(r.get("start", {}).get("line", "?"))
            findings.append(f"{loc} {r.get('check_id', '')}")
    except json.JSONDecodeError:
        pass
    return GateResult(
        "semgrep-baseline",
        passed=proc.returncode == 0,
        detail=f"{len(findings)} new finding(s)",
        findings=findings,
    )


def banned_api_gate(cwd: Path, base: str, files: list[str]) -> GateResult:
    """Direct imports of wrapped SDKs outside the canonical wrapper module.

    Configurable via RATCHET_GATES_BANNED_APIS as comma-separated
    `module:canonical` pairs, e.g.
    `boto3:deps/ses.py,qdrant_client:deps/qdrant.py`. Empty (default) means
    the gate is off — it is opt-in per repo/org because the wrapper layout is
    project-specific. ruff TID251 covers the same class declaratively when the
    repo configures it.
    """
    banned_raw = os.environ.get("RATCHET_GATES_BANNED_APIS", "")
    banned: dict[str, str] = {}
    for pair in banned_raw.split(","):
        if ":" in pair:
            mod, wrapper = pair.split(":", 1)
            banned[mod.strip()] = wrapper.strip()
    if not banned:
        return GateResult("banned-api", True, "SKIPPED: no banned-API config")
    findings = []
    for f in files:
        if not f.endswith(".py"):
            continue
        path = cwd / f
        if not path.exists():
            continue
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        for i, ln in enumerate(lines, 1):
            stripped = ln.strip()
            for mod, wrapper in banned.items():
                if stripped.startswith(f"import {mod}") or stripped.startswith(
                    f"from {mod}"
                ):
                    findings.append(f"{f}:{i}: import {mod} outside {wrapper}")
    return GateResult(
        "banned-api",
        passed=not findings,
        detail=f"{len(findings)} banned import(s)",
        findings=findings,
    )


def free_gates(cwd: Path, files: list[str]) -> GateResult:
    """Cheap, repo-agnostic checks: :latest tags and alembic multi-head."""
    findings = []
    for f in files:
        if f.endswith((".yml", ".yaml")):
            try:
                text = (cwd / f).read_text()
            except OSError:
                continue
            for i, ln in enumerate(text.splitlines(), 1):
                if "image:" in ln and ":latest" in ln:
                    findings.append(f"{f}:{i}: :latest image tag")
    alembic_dir = cwd / "alembic"
    if alembic_dir.exists():
        heads = _run(
            ["python3", "-m", "alembic", "heads"], cwd, check=False
        )
        if heads.returncode == 0:
            count = len([ln for ln in heads.stdout.splitlines() if ln.strip()])
            if count > 1:
                findings.append(f"alembic: {count} heads (must be 1)")
    return GateResult(
        "free-gates",
        passed=not findings,
        detail=f"{len(findings)} finding(s)",
        findings=findings,
    )


def run_all(cwd: Path, severity: str = "ERROR") -> tuple[list[GateResult], bool]:
    base = find_base_commit(cwd)
    files = changed_files(cwd, base)
    gates = [
        ruff_gate(cwd, base, files),
        semgrep_gate(cwd, base, severity),
        banned_api_gate(cwd, base, files),
        free_gates(cwd, files),
    ]
    all_pass = all(g.passed for g in gates)
    return gates, all_pass


def self_check() -> int:
    """Prove the tool's own gates fire before trusting them in CI.

    A gate that silently matches nothing is the exact failure mode this tool
    exists to remove. Both test suites must pass:
    - pytest: ratchet semantics (new fails, legacy passes) in isolated repos
    - semgrep --test: every custom rule matches its fixtures
    """
    failures = 0
    root = REPO_ROOT

    own_python = str(root / ".venv" / "bin" / "python")
    if not Path(own_python).exists():
        own_python = sys.executable
    test_cmd = [own_python, "-m", "pytest", "-q", str(root / "tests")]
    env = dict(
        os.environ,
        PYTHONPATH=str(root / "src"),
        PATH=":".join([str(Path(_tool("ruff") or "ruff").parent), os.environ.get("PATH", "")]),
    )
    r1 = _run(test_cmd, cwd=root, env=env)
    print("[%s] pytest gate suite" % ("PASS" if r1.returncode == 0 else "FAIL"))
    if r1.returncode != 0:
        print(r1.stdout[-2000:])
        print(r1.stderr[-2000:])
        failures += 1

    semgrep_bin = _tool("semgrep") or str(root / ".venv" / "bin" / "semgrep")
    r2 = _run(
        [semgrep_bin, "--test", "--config", str(root / "rules/semgrep/rules/"), str(root / "rules/semgrep/targets/")],
        cwd=root,
    )
    print("[%s] semgrep rule fixtures" % ("PASS" if r2.returncode == 0 else "FAIL"))
    if r2.returncode != 0:
        print(r2.stdout[-2000:])
        print(r2.stderr[-2000:])
        failures += 1

    return 0 if failures == 0 else 1


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="ratchet-gates")
    ap.add_argument("--base", help="override base commit")
    ap.add_argument("--repo", default=".", help="repo path")
    ap.add_argument(
        "--self-check",
        action="store_true",
        help="run the tool's own test suite (pytest + semgrep --test)",
    )
    ap.add_argument("--semgrep-severity", default="ERROR", help="semgrep severity gate")
    args = ap.parse_args()

    if args.self_check:
        return self_check()

    cwd = Path(args.repo).resolve()
    if not (cwd / ".git").exists():
        print("error: not a git repo", file=sys.stderr)
        return 3

    gates, all_pass = run_all(cwd, args.semgrep_severity)
    tool_failure = any(
        g.detail in ("semgrep not found", "ruff not found", "ruff output not JSON")
        for g in gates
    )
    for g in gates:
        mark = "PASS" if g.passed else "FAIL"
        print(f"[{mark}] {g.name}: {g.detail}")
        for finding in g.findings[:10]:
            print(f"       {finding}")

    print("---")
    if tool_failure:
        print("RESULT: TOOLING FAILURE (missing required tool)")
        return 3
    print("RESULT:", "CLEAN" if all_pass else "NEW VIOLATIONS")
    return 0 if all_pass else 2


if __name__ == "__main__":
    sys.exit(main())