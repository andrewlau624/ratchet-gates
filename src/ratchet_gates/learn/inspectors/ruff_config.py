"""What the repository's own ruff config already says."""

from __future__ import annotations

import tomllib
from pathlib import Path

from ratchet_gates.learn.types import Confidence, Signal, SignalKind

CANDIDATE_CODES = (
    "PLC0415",
    "TRY400",
    "UP",
    "TID251",
    "ASYNC",
    "RUF006",
    "RUF100",
    "PGH003",
    "PGH004",
)


class RuffConfigInspector:
    """Reads `select` and `ignore`, and treats them very differently.

    An ignored code is never proposed. Re-enabling a code a team deliberately
    turned off is the documented route to a wall of false positives and a gate
    everybody routes around, so `learn` treats an explicit ignore as a
    standing decision rather than an oversight to correct.
    """

    name = "ruff_config"

    def inspect(self, repo: Path) -> list[Signal]:
        config, origin = self._find(repo)
        if config is None:
            return [
                Signal(
                    SignalKind.RUFF_CODE,
                    code,
                    Confidence.CERTAIN,
                    "no ruff config found; proposing the default code set",
                )
                for code in CANDIDATE_CODES
            ]

        lint = config.get("lint", config)
        selected = {str(c) for c in lint.get("select", [])}
        extended = {str(c) for c in lint.get("extend-select", [])}
        ignored = {str(c) for c in lint.get("ignore", [])}
        active = selected | extended

        signals: list[Signal] = []
        for code in ignored:
            signals.append(
                Signal(
                    SignalKind.RUFF_CODE_BLOCKED,
                    code,
                    Confidence.CERTAIN,
                    f"{origin} explicitly ignores it; learn never re-enables an ignore",
                )
            )
        for code in CANDIDATE_CODES:
            if _covered(code, ignored):
                continue
            if _covered(code, active):
                signals.append(
                    Signal(
                        SignalKind.RUFF_CODE,
                        code,
                        Confidence.CERTAIN,
                        f"already enforced by {origin}; kept so the gate fails on "
                        f"new occurrences rather than only at full-tree lint time",
                    )
                )
            else:
                signals.append(
                    Signal(
                        SignalKind.RUFF_CODE,
                        code,
                        Confidence.CERTAIN,
                        f"not in {origin}; the gate would add it on changed lines only",
                    )
                )

        for pattern in lint.get("per-file-ignores", {}):
            signals.append(
                Signal(
                    SignalKind.OVERRIDE_PATHS,
                    _as_path_glob(str(pattern)),
                    Confidence.CERTAIN,
                    f"{origin} has a per-file-ignore for this path",
                    value=",".join(
                        str(c) for c in lint["per-file-ignores"][pattern]
                    ),
                )
            )
        return signals

    def _find(self, repo: Path) -> tuple[dict | None, str]:
        for name in (".ruff.toml", "ruff.toml"):
            path = repo / name
            if path.is_file():
                return tomllib.loads(path.read_text()), name
        pyproject = repo / "pyproject.toml"
        if pyproject.is_file():
            data = tomllib.loads(pyproject.read_text())
            ruff = data.get("tool", {}).get("ruff")
            if ruff is not None:
                return ruff, "pyproject.toml [tool.ruff]"
        return None, ""


def _covered(code: str, configured: set[str]) -> bool:
    """`UP` in the config covers `UP045`, and vice versa."""
    return any(code.startswith(c) or c.startswith(code) for c in configured)


def _as_path_glob(pattern: str) -> str:
    """Ruff matches a bare `*_test.py` against the basename; our globs do not.

    Anchoring the translation here keeps the generated config meaning what
    the source config meant, instead of silently narrowing to the repo root.
    """
    return pattern if "/" in pattern else f"**/{pattern}"
