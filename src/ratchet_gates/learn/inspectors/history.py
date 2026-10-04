"""Conventions reviewers actually enforce, mined from merged pull requests.

The written convention and the enforced convention are different sets. The
audit behind this tool found function-local imports recurring on 320 distinct
pull requests while the rule sat in the repo's agent instructions, in a review
bot's config, and in a semgrep target — three places that stated it and none
that enforced it. This inspector reads what reviewers keep saying, which is a
better predictor of what is worth gating than what the docs claim.

Opt-in (`--from-history`) because it needs a token and takes minutes: the
GraphQL page size is capped and a large repository is thousands of pull
requests.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path

from ratchet_gates.learn.types import Confidence, Signal, SignalKind

#: Comment phrasing -> the code that decides it mechanically. Deliberately
#: small: a cluster with no entry here is reported as a question, not guessed
#: into a rule.
CLUSTERS: tuple[tuple[str, str, str], ...] = (
    (r"import .*(inside|within|local to) (the )?function|move .*import to the top", "PLC0415", "function-local imports"),
    (r"logger\.exception|lose[sd]? the traceback|use exception not error", "TRY400", "logger.error where exception belongs"),
    (r"bare except|except:\s*pass|swallow(s|ing)? the (error|exception)", "", "silently swallowed exceptions"),
    (r"autospec|patch\(.*\) without", "", "mock.patch without autospec"),
    (r"create_task|dangling task|task is not awaited", "RUF006", "dangling asyncio tasks"),
    (r"type:\s*ignore|blanket noqa", "PGH003", "blanket suppressions"),
    (r"service class|random functions|proper entrypoint", "", "one owner per domain concept"),
    (r"out of scope|pre-?existing|not in this diff", "", "scope deferral"),
)

QUERY = """
query($owner:String!,$name:String!,$cursor:String){
  repository(owner:$owner,name:$name){
    pullRequests(states:MERGED,first:50,after:$cursor,
                 orderBy:{field:UPDATED_AT,direction:DESC}){
      pageInfo{hasNextPage endCursor}
      nodes{ number reviewThreads(first:20){ nodes{ comments(first:5){ nodes{ body } } } } }
    }
  }
}
"""


class HistoryInspector:
    name = "history"

    def __init__(self, max_pages: int = 10) -> None:
        self.max_pages = max_pages

    def inspect(self, repo: Path) -> list[Signal]:
        slug = self._slug(repo)
        if not slug:
            return [
                Signal(
                    SignalKind.JUDGEMENT,
                    "history unavailable",
                    Confidence.SUGGESTED,
                    "no GitHub remote found; --from-history needs one",
                )
            ]
        owner, name = slug
        comments = self._fetch(owner, name)
        if comments is None:
            return [
                Signal(
                    SignalKind.JUDGEMENT,
                    "history unavailable",
                    Confidence.SUGGESTED,
                    "gh CLI not authenticated or the API call failed; "
                    "run `gh auth login` and retry",
                )
            ]

        hits: dict[str, set[int]] = defaultdict(set)
        examples: dict[str, str] = {}
        for pr_number, body in comments:
            lowered = body.lower()
            for pattern, code, label in CLUSTERS:
                if re.search(pattern, lowered):
                    key = f"{label}|{code}"
                    hits[key].add(pr_number)
                    examples.setdefault(key, body.strip().replace("\n", " ")[:110])

        out: list[Signal] = []
        for key, prs in sorted(hits.items(), key=lambda kv: -len(kv[1])):
            label, code = key.split("|", 1)
            evidence = (
                f'{len(prs)} merged PR(s) carry this finding — e.g. '
                f'"{examples[key]}"'
            )
            if code:
                out.append(
                    Signal(SignalKind.RUFF_CODE, code, Confidence.CERTAIN, evidence)
                )
            else:
                out.append(
                    Signal(
                        SignalKind.JUDGEMENT, label, Confidence.SUGGESTED, evidence
                    )
                )
        return out

    def _slug(self, repo: Path) -> tuple[str, str] | None:
        try:
            url = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=repo,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
        except (subprocess.CalledProcessError, OSError):
            return None
        match = re.search(r"github\.com[:/]([^/]+)/(.+?)(?:\.git)?$", url)
        return (match.group(1), match.group(2)) if match else None

    def _fetch(self, owner: str, name: str) -> list[tuple[int, str]] | None:
        if not (os.environ.get("GITHUB_TOKEN") or _gh_available()):
            return None
        collected: list[tuple[int, str]] = []
        cursor: str | None = None
        for _ in range(self.max_pages):
            command = [
                "gh", "api", "graphql",
                "-f", f"query={QUERY}",
                "-F", f"owner={owner}",
                "-F", f"name={name}",
            ]
            if cursor:
                command += ["-F", f"cursor={cursor}"]
            proc = subprocess.run(
                command, text=True, capture_output=True, check=False
            )
            if proc.returncode != 0:
                return collected or None
            try:
                page = json.loads(proc.stdout)["data"]["repository"]["pullRequests"]
            except (KeyError, json.JSONDecodeError, TypeError):
                return collected or None
            for node in page["nodes"]:
                for thread in node["reviewThreads"]["nodes"]:
                    for comment in thread["comments"]["nodes"]:
                        collected.append((node["number"], comment["body"]))
            if not page["pageInfo"]["hasNextPage"]:
                break
            cursor = page["pageInfo"]["endCursor"]
        return collected


def _gh_available() -> bool:
    try:
        return (
            subprocess.run(
                ["gh", "auth", "token"], capture_output=True, text=True, check=False
            ).returncode
            == 0
        )
    except OSError:
        return False
