"""What an inspector reports.

The distinction that matters is `Confidence`. A signal READ from a rule file
or from the directory layout is a fact about the repository. A signal INFERRED
from prose is a guess, and guesses are written into the config commented out
with their evidence attached, so adopting one is a human edit.

That is the same contract `rules/reviewer-prompt.md` puts on a reviewer: a
claim without evidence is a suggestion, not a finding. A tool that enabled
rules it could not justify would be generating exactly the unverified rules
this project exists to stop shipping.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Confidence(StrEnum):
    CERTAIN = "certain"
    SUGGESTED = "suggested"


class SignalKind(StrEnum):
    RUFF_CODE = "ruff_code"
    #: A code the repo explicitly ignores. Never enabled, at any confidence.
    RUFF_CODE_BLOCKED = "ruff_code_blocked"
    BANNED_API = "banned_api"
    SEMGREP_DIR = "semgrep_dir"
    FREE_GATE = "free_gate"
    OVERRIDE_PATHS = "override_paths"
    #: Something real that no deterministic rule covers. Routed to the
    #: reviewer prompt rather than invented as a gate.
    JUDGEMENT = "judgement"


@dataclass(frozen=True)
class Signal:
    kind: SignalKind
    key: str
    confidence: Confidence
    evidence: str
    value: str = ""
