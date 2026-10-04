"""Shared vocabulary: gate outcomes and the resolved policy a gate runs under.

Two things live here and nothing else. The enums give every closed set in the
tool a name — a gate's outcome used to be a bool plus a detail string that
`main()` pattern-matched against three literals, so rewording a message
silently downgraded a tooling failure to a pass. The policy dataclasses are
what `config/` produces and `gates/` consumes: a gate never reads the
environment or a config file, it is handed the answer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType


class Verdict(StrEnum):
    """The run's overall outcome. Maps 1:1 onto the process exit code."""

    CLEAN = "CLEAN"
    NEW_VIOLATIONS = "NEW_VIOLATIONS"
    TOOLING_FAILURE = "TOOLING_FAILURE"

    @property
    def exit_code(self) -> int:
        match self:
            case Verdict.CLEAN:
                return 0
            case Verdict.NEW_VIOLATIONS:
                return 2
            case Verdict.TOOLING_FAILURE:
                return 3
        raise NotImplementedError(f"no exit code defined for {self!r}")


class GateStatus(StrEnum):
    """One gate's outcome.

    SKIPPED is a pass with a stated reason (the gate is off, or has nothing to
    look at). TOOLING_FAILURE is NOT a pass: a gate that could not run has
    measured nothing, and reporting that as success is how a green check comes
    to mean nothing.
    """

    PASS = "PASS"
    FAIL = "FAIL"
    SKIPPED = "SKIPPED"
    TOOLING_FAILURE = "TOOLING_FAILURE"


class GateName(StrEnum):
    RUFF_DIFF = "ruff-diff"
    SEMGREP_BASELINE = "semgrep-baseline"
    BANNED_API = "banned-api"
    FREE_GATES = "free-gates"


class Severity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class GateResult:
    name: GateName
    status: GateStatus
    detail: str = ""
    findings: tuple[str, ...] = ()


def verdict_of(results: list[GateResult]) -> Verdict:
    """Fold gate outcomes into the run verdict.

    Tooling failure outranks violations: if a gate could not run we do not know
    whether the diff is clean, and saying so is the whole contract.
    """
    if any(r.status is GateStatus.TOOLING_FAILURE for r in results):
        return Verdict.TOOLING_FAILURE
    if any(r.status is GateStatus.FAIL for r in results):
        return Verdict.NEW_VIOLATIONS
    return Verdict.CLEAN


@dataclass(frozen=True)
class RuffPolicy:
    codes: tuple[str, ...]

    @property
    def enabled(self) -> bool:
        return bool(self.codes)


@dataclass(frozen=True)
class SemgrepPolicy:
    """Intent, not resolved paths.

    `bundled_rules` stays a declared intention all the way to the gate so that
    "you asked for the shipped rules and they are not installed" is a tooling
    failure. Resolving it to an empty directory list here would turn a broken
    install into a silent pass — the exact shape of issue #1.
    """

    severity: Severity
    bundled_rules: bool
    extra_rule_dirs: tuple[str, ...]
    disabled: frozenset[str]

    @property
    def enabled(self) -> bool:
        return self.bundled_rules or bool(self.extra_rule_dirs)


@dataclass(frozen=True)
class FreeGatePolicy:
    latest_image_tag: bool
    alembic_single_head: bool

    @property
    def enabled(self) -> bool:
        return self.latest_image_tag or self.alembic_single_head


@dataclass(frozen=True)
class Profile:
    """The fully resolved policy for one path.

    `source` is the provenance trail ("built-in default", then each config
    layer and override that touched it) and is printed with the gate output so
    the log answers "which policy ran" without a directory walk.
    """

    name: str
    ruff: RuffPolicy
    semgrep: SemgrepPolicy
    banned_api: Mapping[str, str]
    free_gates: FreeGatePolicy
    source: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        # Freeze the mapping so a gate cannot mutate the policy it was handed.
        object.__setattr__(self, "banned_api", MappingProxyType(dict(self.banned_api)))

    @property
    def any_gate_enabled(self) -> bool:
        return (
            self.ruff.enabled
            or self.semgrep.enabled
            or bool(self.banned_api)
            or self.free_gates.enabled
        )


@dataclass(frozen=True)
class GateContext:
    """Everything a gate needs, assembled once by GateService."""

    repo: Path
    base: str
    changed_files: tuple[str, ...]
    root_profile: Profile
    #: path (repo-relative) -> the policy that applies to it
    resolve: Callable[[str], Profile]
    #: path -> the line numbers this diff added. The ratchet, precomputed once.
    added_lines: Mapping[str, frozenset[int]] = field(default_factory=dict)


class ConfigError(Exception):
    """A config file the tool refuses to guess about.

    Raised for unknown keys, contradictory merge directives, and policies that
    resolve to no enabled gates. Every one of these would otherwise be a silent
    disable, which is the defect class this project exists to remove.
    """
