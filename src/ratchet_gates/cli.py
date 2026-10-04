"""Command-line surface. Parse arguments, call a service, print, exit.

No gate logic, no config merging and no inspection happens here. Each command
is a handful of lines because the work lives behind one named hop:
`GateService`, `ConfigLoader`, `LearnService`.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ratchet_gates.config import CONFIG_FILENAME, ConfigLoader
from ratchet_gates.config.loader import PROFILES_DIR
from ratchet_gates.gates import GateService
from ratchet_gates.learn.render import render_toml
from ratchet_gates.learn.service import LearnService
from ratchet_gates.report import (
    ReportService,
    RunReport,
    render_aggregate,
    render_run_markdown,
)
from ratchet_gates.selfcheck import self_check
from ratchet_gates.types import ConfigError, GateStatus, Verdict

SUBCOMMANDS = ("learn", "profiles", "config", "report")

MARK = {
    GateStatus.PASS: "PASS",
    GateStatus.FAIL: "FAIL",
    GateStatus.SKIPPED: "SKIP",
    GateStatus.TOOLING_FAILURE: "FAIL",
}

RESULT_LINE = {
    Verdict.CLEAN: "RESULT: CLEAN",
    Verdict.NEW_VIOLATIONS: "RESULT: NEW VIOLATIONS",
    Verdict.TOOLING_FAILURE: "RESULT: TOOLING FAILURE (a gate could not run)",
}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command, rest = ("run", args)
    if args and args[0] in SUBCOMMANDS:
        command, rest = args[0], args[1:]

    try:
        match command:
            case "learn":
                return _learn(rest)
            case "profiles":
                return _profiles(rest)
            case "config":
                return _config(rest)
            case "report":
                return _report(rest)
            case "run":
                return _run(rest)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return Verdict.TOOLING_FAILURE.exit_code
    raise NotImplementedError(f"unhandled command {command!r}")


def _run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ratchet-gates")
    parser.add_argument("--repo", default=".", help="repository to gate")
    parser.add_argument("--base", help="override the ratchet's base commit")
    parser.add_argument("--profile", help="named profile to start from")
    parser.add_argument("--ruff-codes", help="replace the ruff code set for this run")
    parser.add_argument(
        "--semgrep-severity",
        help="which semgrep severities to REPORT (ERROR or WARNING). This is a "
        "rule filter, not an advisory switch: most bundled rules declare ERROR, "
        "so WARNING hides them. Use --advisory to adopt without blocking.",
    )
    parser.add_argument(
        "--json-out",
        help="also write a machine-readable run record here. Stack these up "
        "and `ratchet-gates report` tells you which rules actually fire.",
    )
    parser.add_argument(
        "--advisory",
        action="store_true",
        help="run every gate and report findings, but always exit 0. The "
        "honest way to adopt before making the check required.",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="run the tool's own suite (pytest + semgrep --test)",
    )
    args = parser.parse_args(argv)

    if args.self_check:
        return self_check()

    repo = Path(args.repo).resolve()
    if not (repo / ".git").exists():
        print(f"error: {repo} is not a git repository", file=sys.stderr)
        return Verdict.TOOLING_FAILURE.exit_code

    service = GateService.build(
        repo,
        profile_name=args.profile,
        ruff_codes=args.ruff_codes,
        semgrep_severity=args.semgrep_severity,
    )
    results, verdict, base = service.run(args.base)

    print(f"policy: {' -> '.join(service.config.root.source)}")
    print(f"base:   {base[:12]}")
    for result in results:
        print(f"[{MARK[result.status]}] {result.name.value}: {result.detail}")
        for finding in result.findings[:10]:
            print(f"       {finding.render()}")
        if len(result.findings) > 10:
            print(f"       ... and {len(result.findings) - 10} more")
    if args.json_out:
        ReportService().write(
            RunReport(
                repo=str(repo),
                base=base,
                verdict=verdict,
                advisory=args.advisory,
                policy=service.config.root.source,
                gates=tuple(results),
                context=_ci_context(),
            ),
            Path(args.json_out),
        )

    print("---")
    print(RESULT_LINE[verdict])
    if args.advisory and verdict is not Verdict.CLEAN:
        print(
            "ADVISORY MODE: exiting 0 despite the result above. Every gate ran "
            "and every finding is listed; nothing was filtered out to achieve "
            "this. Drop --advisory to start blocking."
        )
        return 0
    return verdict.exit_code


def _learn(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ratchet-gates learn")
    parser.add_argument("--repo", default=".", help="repository to learn from")
    parser.add_argument(
        "--out",
        help=f"write to this path instead of stdout (usually {CONFIG_FILENAME})",
    )
    parser.add_argument(
        "--from-history",
        action="store_true",
        help="also mine merged pull requests for conventions reviewers enforce",
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    result = LearnService().learn(repo, from_history=args.from_history)
    rendered = render_toml(result)

    if not args.out:
        print(rendered, end="")
        return 0
    destination = Path(args.out)
    if destination.exists():
        print(
            f"error: {destination} already exists. Writing over a reviewed "
            f"config would discard decisions somebody made; diff against a "
            f"fresh `learn` run instead.",
            file=sys.stderr,
        )
        return 1
    destination.write_text(rendered)
    print(f"wrote {destination}. Review every line before committing it.")
    return 0


def _profiles(argv: list[str]) -> int:
    argparse.ArgumentParser(prog="ratchet-gates profiles").parse_args(argv)
    for path in sorted(PROFILES_DIR.glob("*.toml")):
        summary = next(
            (
                line.lstrip("# ").rstrip()
                for line in path.read_text().splitlines()
                if line.startswith("#") and len(line) > 3
            ),
            "",
        )
        print(f"{path.stem:12} {summary}")
    return 0


def _config(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ratchet-gates config")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--profile")
    parser.add_argument(
        "--path", help="show the policy that applies to this repo-relative path"
    )
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve()
    resolved = ConfigLoader(repo).load(profile_name=args.profile)
    profile = resolved.for_path(args.path) if args.path else resolved.root

    print(f"path:    {args.path or '<repository root>'}")
    print(f"policy:  {' -> '.join(profile.source)}")
    print(f"ruff:    {', '.join(profile.ruff.codes) or '(none)'}")
    print(
        f"semgrep: severity={profile.semgrep.severity.value} "
        f"bundled={profile.semgrep.bundled_rules} "
        f"extra={list(profile.semgrep.extra_rule_dirs)} "
        f"disabled={sorted(profile.semgrep.disabled) or '[]'}"
    )
    print(f"banned:  {dict(profile.banned_api) or '(gate off)'}")
    print(
        f"free:    latest_image_tag={profile.free_gates.latest_image_tag} "
        f"alembic_single_head={profile.free_gates.alembic_single_head}"
    )
    if resolved.overrides:
        print(f"overrides defined: {len(resolved.overrides)}")
        for override in resolved.overrides:
            print(f"  #{override.index} {', '.join(override.paths)}")
    return 0


def _report(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="ratchet-gates report")
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="run records written by --json-out, or directories of them",
    )
    parser.add_argument("--repo", default=".", help="repo whose policy to compare against")
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument(
        "--one",
        action="store_true",
        help="render a single run (for a job summary or PR comment)",
    )
    args = parser.parse_args(argv)

    service = ReportService()
    reports = service.load(args.paths)
    if not reports:
        print("no run records found", file=sys.stderr)
        return 1
    if args.one:
        print(render_run_markdown(reports[-1]), end="")
        return 0

    configured = set(
        ConfigLoader(Path(args.repo).resolve()).load().root.ruff.codes
    )
    print(
        render_aggregate(
            service.aggregate(reports, configured), markdown=args.markdown
        ),
        end="",
    )
    return 0


def _ci_context() -> dict[str, str]:
    """Whatever the CI provider will tell us, so a record is traceable."""
    keys = {
        "repository": "GITHUB_REPOSITORY",
        "ref": "GITHUB_REF_NAME",
        "sha": "GITHUB_SHA",
        "run_id": "GITHUB_RUN_ID",
        "actor": "GITHUB_ACTOR",
    }
    return {name: os.environ[var] for name, var in keys.items() if os.environ.get(var)}


if __name__ == "__main__":
    sys.exit(main())
