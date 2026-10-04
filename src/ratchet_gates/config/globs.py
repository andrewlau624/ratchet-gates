"""Gitignore-style glob matching for override `paths`.

`fnmatch` treats `*` as crossing directory separators and `pathlib.match` only
grew `**` support in 3.13, so neither does what a reader expects from
`tests/**` or `**/*_test.py`. This is the smallest thing that behaves the way
the config file claims.
"""

from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=256)
def compile_glob(pattern: str) -> re.Pattern[str]:
    """Translate one glob to an anchored regex.

    `**/` matches zero or more leading directories, `**` matches anything,
    `*` and `?` stop at a separator. A pattern ending in `/` or `/**` also
    matches the directory's whole subtree.
    """
    if pattern.endswith("/"):
        pattern += "**"
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


def matches(pattern: str, path: str) -> bool:
    return compile_glob(pattern).match(path) is not None


def matches_any(patterns: tuple[str, ...], path: str) -> bool:
    return any(matches(p, path) for p in patterns)
