"""What the directory tree says about the repository's conventions."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from ratchet_gates.learn.types import Confidence, Signal, SignalKind

#: Directory names that conventionally hold one wrapper module per service.
WRAPPER_DIRS = ("deps", "clients", "integrations", "adapters", "vendor")

#: Third-party clients worth wrapping. Presence of an import here is read,
#: not guessed, so a match is CERTAIN.
WRAPPABLE = (
    "boto3",
    "redis",
    "qdrant_client",
    "httpx",
    "openai",
    "anthropic",
    "sqlalchemy",
    "prometheus_client",
    "stripe",
    "elasticsearch",
    "pymongo",
    "kafka",
    "snowflake",
)

IMPORT = re.compile(r"^\s*(?:from|import)\s+([A-Za-z_][\w.]*)", re.MULTILINE)
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".tox"}

#: `qdrant_client` is wrapped by `qdrant.py`, `prometheus_client` by
#: `prometheus.py`. Strip the suffix before comparing names.
NAME_SUFFIXES = ("_client", "3", "_sdk", "-python")


class LayoutInspector:
    name = "layout"

    def inspect(self, repo: Path) -> list[Signal]:
        signals: list[Signal] = []
        signals += self._wrappers(repo)
        signals += self._free_gates(repo)
        signals += self._test_layout(repo)
        return signals

    def _wrappers(self, repo: Path) -> list[Signal]:
        """Attribute each SDK to the module that wraps it.

        "A module in deps/ that imports boto3" is far too loose a definition
        of "the boto3 wrapper" — on a real repository it attributed redis to
        a rate limiter and sqlalchemy to a test file. Only a NAME match is
        treated as established (`redis.py` wraps redis); everything else is
        reported as a suggestion listing the candidates, because banning an
        import org-wide on a bad guess produces exactly the wall of false
        positives that gets a gate switched off in week one.
        """
        importers: dict[str, list[str]] = defaultdict(list)
        for directory in self._candidate_dirs(repo):
            rel_dir = directory.relative_to(repo)
            for module in sorted(directory.glob("*.py")):
                if not _is_library_module(module.name):
                    continue
                try:
                    imported = set(IMPORT.findall(module.read_text()))
                except OSError:
                    continue
                for sdk in WRAPPABLE:
                    if any(
                        name == sdk or name.startswith(f"{sdk}.")
                        for name in imported
                    ):
                        importers[sdk].append(f"{rel_dir}/{module.name}")

        out: list[Signal] = []
        for sdk, paths in sorted(importers.items()):
            named = [p for p in paths if _name_matches(sdk, Path(p).stem)]
            if len(named) == 1:
                out.append(
                    Signal(
                        SignalKind.BANNED_API,
                        sdk,
                        Confidence.CERTAIN,
                        f"{named[0]} is named for {sdk} and imports it; "
                        f"it is the wrapper",
                        value=named[0],
                    )
                )
                continue
            out.append(
                Signal(
                    SignalKind.BANNED_API,
                    sdk,
                    Confidence.SUGGESTED,
                    f"imported by {', '.join(paths)} — no module is named for "
                    f"{sdk}, so which one is the wrapper is a guess",
                    value=paths[0],
                )
            )
        return out

    def _candidate_dirs(self, repo: Path) -> list[Path]:
        found: list[Path] = []
        for path in repo.rglob("*"):
            if not path.is_dir() or path.name not in WRAPPER_DIRS:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            found.append(path)
        return found

    def _free_gates(self, repo: Path) -> list[Signal]:
        out: list[Signal] = []
        alembic = repo / "alembic"
        out.append(
            Signal(
                SignalKind.FREE_GATE,
                "alembic_single_head",
                Confidence.CERTAIN,
                "alembic/ is present" if alembic.is_dir() else "no alembic/ directory",
                value="true" if alembic.is_dir() else "false",
            )
        )
        manifests = self._has_manifests(repo)
        out.append(
            Signal(
                SignalKind.FREE_GATE,
                "latest_image_tag",
                Confidence.CERTAIN,
                "found YAML declaring container images"
                if manifests
                else "no container image manifests found",
                value="true" if manifests else "false",
            )
        )
        return out

    def _own_files(self, repo: Path, pattern: str) -> list[Path]:
        """Repo files only — a vendored virtualenv is not a convention."""
        return [
            p
            for p in repo.rglob(pattern)
            if not any(part in SKIP_DIRS for part in p.parts)
        ]

    def _has_manifests(self, repo: Path) -> bool:
        for path in repo.rglob("*.y*ml"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            try:
                if "image:" in path.read_text():
                    return True
            except OSError:
                continue
        return False

    def _test_layout(self, repo: Path) -> list[Signal]:
        suffix = len(self._own_files(repo, "*_test.py"))
        prefix = len(self._own_files(repo, "test_*.py"))
        if not suffix and not prefix:
            return []
        pattern = "**/*_test.py" if suffix >= prefix else "**/test_*.py"
        return [
            Signal(
                SignalKind.OVERRIDE_PATHS,
                pattern,
                Confidence.SUGGESTED,
                f"{max(suffix, prefix)} test files use this naming; an override "
                f"here is where teams usually relax a code, but relaxing one is "
                f"your decision, not a fact about the repo",
            )
        ]


def _is_library_module(filename: str) -> bool:
    """Tests and private modules are not the wrapper for anything."""
    stem = filename[:-3]
    return not (
        stem.startswith(("_", "test_")) or stem.endswith("_test") or stem == "conftest"
    )


def _name_matches(sdk: str, stem: str) -> bool:
    base = sdk
    for suffix in NAME_SUFFIXES:
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return stem in (sdk, base) or stem.replace("_", "") == base.replace("_", "")
