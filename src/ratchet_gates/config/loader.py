"""Turn configuration into one resolved policy per path.

Control flow is a single pass with no hidden lookups. `ConfigLoader.load()`
stacks five layers in a fixed order and returns a `ResolvedConfig`; asking it
`for_path(p)` applies any matching `[[override]]` blocks on top. There is one
config file, one resolution step, and the provenance of every setting is
carried on the Profile so the gate output can state which policy ran.

Layer order, lowest first:

    built-in default -> named profile -> .ratchet-gates.toml root tables
    -> environment -> CLI flags

`[[override]]` blocks sit between the root tables and the environment: they
refine the file's own policy, and an explicit flag or env var is a deliberate
one-off that outranks the whole file.

Every parse error here is fatal. An unknown key, a contradictory merge
directive, or a policy with no enabled gates aborts the run rather than
resolving to something plausible. A typo that silently disables a gate is the
defect class this tool exists to remove, and reporting PASS because nothing
ran is indistinguishable from reporting PASS because nothing was wrong.
"""

from __future__ import annotations

import difflib
import os
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path

from ratchet_gates.config.globs import matches_any
from ratchet_gates.types import (
    ConfigError,
    FreeGatePolicy,
    Profile,
    RuffPolicy,
    SemgrepPolicy,
    Severity,
)

CONFIG_FILENAME = ".ratchet-gates.toml"
PROFILES_DIR = Path(__file__).resolve().parent / "profiles"

ENV_RUFF_CODES = "RATCHET_GATES_RUFF_CODES"
ENV_BANNED_APIS = "RATCHET_GATES_BANNED_APIS"

ROOT_KEYS = frozenset(
    {"profile", "ruff", "semgrep", "banned_api", "free_gates", "override"}
)
RUFF_KEYS = frozenset({"codes"})
RUFF_OVERRIDE_KEYS = frozenset({"codes", "remove"})
SEMGREP_KEYS = frozenset(
    {"severity", "bundled_rules", "extra_rule_dirs", "disabled"}
)
SEMGREP_OVERRIDE_KEYS = frozenset({"disabled"})
FREE_KEYS = frozenset({"latest_image_tag", "alembic_single_head"})
#: alembic single-head is a property of the repository, not of a file, so
#: there is no path to attribute it to. Allowing it in an override would make
#: "which block turned this off" unanswerable.
FREE_OVERRIDE_KEYS = frozenset({"latest_image_tag"})
REPO_GLOBAL_KEYS = FREE_KEYS - FREE_OVERRIDE_KEYS
OVERRIDE_KEYS = frozenset({"paths", "ruff", "semgrep", "banned_api", "free_gates"})


def _reject_unknown(where: str, got: dict, allowed: frozenset[str]) -> None:
    for key in got:
        if key in allowed:
            continue
        hint = difflib.get_close_matches(key, sorted(allowed), n=1)
        suffix = f" Did you mean {hint[0]!r}?" if hint else ""
        if key in REPO_GLOBAL_KEYS:
            raise ConfigError(
                f"{where}: {key!r} is repo-global and cannot appear in an "
                f"[[override]] block — there is no single path to attribute it "
                f"to. Set it in the root [free_gates] table instead."
            )
        raise ConfigError(
            f"{where}: unknown key {key!r}.{suffix} "
            f"Valid keys: {', '.join(sorted(allowed))}."
        )


def _as_str_tuple(where: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{where}: expected a list of strings, got {value!r}")
    return tuple(value)


def _as_bool(where: str, value: object) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{where}: expected true or false, got {value!r}")
    return value


@dataclass(frozen=True)
class Override:
    """A partial policy patch scoped to a set of path globs."""

    index: int
    paths: tuple[str, ...]
    ruff_codes: tuple[str, ...] | None = None
    ruff_remove: frozenset[str] = frozenset()
    semgrep_disabled: frozenset[str] = frozenset()
    banned_api: dict[str, str] | None = None
    latest_image_tag: bool | None = None

    @property
    def label(self) -> str:
        return f"override #{self.index} ({', '.join(self.paths)})"

    def apply(self, profile: Profile) -> Profile:
        ruff = profile.ruff
        if self.ruff_codes is not None:
            ruff = RuffPolicy(codes=self.ruff_codes)
        elif self.ruff_remove:
            ruff = RuffPolicy(
                codes=tuple(c for c in ruff.codes if c not in self.ruff_remove)
            )
        semgrep = profile.semgrep
        if self.semgrep_disabled:
            semgrep = replace(
                semgrep, disabled=semgrep.disabled | self.semgrep_disabled
            )
        free = profile.free_gates
        if self.latest_image_tag is not None:
            free = replace(free, latest_image_tag=self.latest_image_tag)
        return replace(
            profile,
            ruff=ruff,
            semgrep=semgrep,
            banned_api=(
                self.banned_api if self.banned_api is not None else profile.banned_api
            ),
            free_gates=free,
            source=(*profile.source, self.label),
        )


@dataclass(frozen=True)
class ResolvedConfig:
    root: Profile
    overrides: tuple[Override, ...] = ()

    def for_path(self, path: str) -> Profile:
        """Policy for one repo-relative path.

        All matching overrides apply in declaration order; later blocks win on
        conflict. Order is the rule rather than a glob-specificity heuristic,
        because "which of these two patterns is more specific" is a question
        readers answer differently from the implementation.
        """
        profile = self.root
        for override in self.overrides:
            if matches_any(override.paths, path):
                profile = override.apply(profile)
        return profile


class ConfigLoader:
    """Finds, parses and merges configuration into a `ResolvedConfig`."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo

    # -- public ---------------------------------------------------------

    def load(
        self,
        *,
        profile_name: str | None = None,
        cli_ruff_codes: str | None = None,
        cli_severity: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ResolvedConfig:
        env = os.environ if env is None else env

        document = self._read_repo_config()
        _reject_unknown(CONFIG_FILENAME, document, ROOT_KEYS)

        chosen = profile_name or document.get("profile") or "default"
        if not isinstance(chosen, str):
            raise ConfigError(f"{CONFIG_FILENAME}: 'profile' must be a string")

        profile = self._load_named_profile(chosen)
        profile = self._apply_tables(profile, document, source=CONFIG_FILENAME)
        profile = self._apply_env(profile, env)
        profile = self._apply_cli(profile, cli_ruff_codes, cli_severity)

        if not profile.any_gate_enabled:
            raise ConfigError(
                "the resolved policy enables no gates. A run that checks "
                "nothing reports PASS for the same reason a clean run does; "
                "refusing rather than claiming success."
            )

        overrides = self._parse_overrides(document.get("override", []))
        return ResolvedConfig(root=profile, overrides=overrides)

    # -- layers ---------------------------------------------------------

    def _read_repo_config(self) -> dict:
        path = self.repo / CONFIG_FILENAME
        if not path.exists():
            return {}
        try:
            return tomllib.loads(path.read_text())
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"{CONFIG_FILENAME}: {exc}") from exc

    def _load_named_profile(self, name: str) -> Profile:
        path = PROFILES_DIR / f"{name}.toml"
        if not path.exists():
            available = sorted(p.stem for p in PROFILES_DIR.glob("*.toml"))
            raise ConfigError(
                f"unknown profile {name!r}. Available: {', '.join(available)}."
            )
        document = tomllib.loads(path.read_text())
        _reject_unknown(f"profile {name!r}", document, ROOT_KEYS)
        empty = Profile(
            name=name,
            ruff=RuffPolicy(codes=()),
            semgrep=SemgrepPolicy(
                severity=Severity.ERROR,
                bundled_rules=False,
                extra_rule_dirs=(),
                disabled=frozenset(),
            ),
            banned_api={},
            free_gates=FreeGatePolicy(
                latest_image_tag=False, alembic_single_head=False
            ),
            source=(),
        )
        return self._apply_tables(empty, document, source=f"profile {name!r}")

    def _apply_tables(self, profile: Profile, document: dict, *, source: str) -> Profile:
        if not document:
            return profile
        ruff = profile.ruff
        if (table := document.get("ruff")) is not None:
            _reject_unknown(f"{source} [ruff]", table, RUFF_KEYS)
            if "codes" in table:
                ruff = RuffPolicy(
                    codes=_as_str_tuple(f"{source} [ruff].codes", table["codes"])
                )

        semgrep = profile.semgrep
        if (table := document.get("semgrep")) is not None:
            _reject_unknown(f"{source} [semgrep]", table, SEMGREP_KEYS)
            if "severity" in table:
                raw = table["severity"]
                try:
                    severity = Severity(str(raw).upper())
                except ValueError as exc:
                    valid = ", ".join(s.value for s in Severity)
                    raise ConfigError(
                        f"{source} [semgrep].severity: {raw!r} is not one of {valid}"
                    ) from exc
                semgrep = replace(semgrep, severity=severity)
            if "bundled_rules" in table:
                semgrep = replace(
                    semgrep,
                    bundled_rules=_as_bool(
                        f"{source} [semgrep].bundled_rules", table["bundled_rules"]
                    ),
                )
            if "extra_rule_dirs" in table:
                semgrep = replace(
                    semgrep,
                    extra_rule_dirs=_as_str_tuple(
                        f"{source} [semgrep].extra_rule_dirs", table["extra_rule_dirs"]
                    ),
                )
            if "disabled" in table:
                semgrep = replace(
                    semgrep,
                    disabled=frozenset(
                        _as_str_tuple(
                            f"{source} [semgrep].disabled", table["disabled"]
                        )
                    ),
                )

        banned = profile.banned_api
        if (table := document.get("banned_api")) is not None:
            if not all(isinstance(v, str) for v in table.values()):
                raise ConfigError(
                    f"{source} [banned_api]: every value must be the path of the "
                    f"wrapper module that should be imported instead"
                )
            banned = dict(table)

        free = profile.free_gates
        if (table := document.get("free_gates")) is not None:
            _reject_unknown(f"{source} [free_gates]", table, FREE_KEYS)
            for key in FREE_KEYS & table.keys():
                free = replace(
                    free, **{key: _as_bool(f"{source} [free_gates].{key}", table[key])}
                )

        return replace(
            profile,
            ruff=ruff,
            semgrep=semgrep,
            banned_api=banned,
            free_gates=free,
            source=(*profile.source, source) if document else profile.source,
        )

    def _apply_env(self, profile: Profile, env: dict[str, str]) -> Profile:
        # An empty value means "not set". os.environ.get(k, default) returns ""
        # for a variable that is exported but blank, which previously built an
        # empty extend-select and disabled every rule the gate adds.
        if codes := env.get(ENV_RUFF_CODES, "").strip():
            profile = replace(
                profile,
                ruff=RuffPolicy(codes=_split_codes(codes)),
                source=(*profile.source, f"${ENV_RUFF_CODES}"),
            )
        if raw := env.get(ENV_BANNED_APIS, "").strip():
            profile = replace(
                profile,
                banned_api=_parse_banned_pairs(raw),
                source=(*profile.source, f"${ENV_BANNED_APIS}"),
            )
        return profile

    def _apply_cli(
        self, profile: Profile, ruff_codes: str | None, severity: str | None
    ) -> Profile:
        if ruff_codes and ruff_codes.strip():
            profile = replace(
                profile,
                ruff=RuffPolicy(codes=_split_codes(ruff_codes)),
                source=(*profile.source, "--ruff-codes"),
            )
        if severity:
            try:
                parsed = Severity(severity.upper())
            except ValueError as exc:
                valid = ", ".join(s.value for s in Severity)
                raise ConfigError(
                    f"--semgrep-severity: {severity!r} is not one of {valid}"
                ) from exc
            profile = replace(
                profile, semgrep=replace(profile.semgrep, severity=parsed)
            )
        return profile

    # -- overrides ------------------------------------------------------

    def _parse_overrides(self, raw: object) -> tuple[Override, ...]:
        if not isinstance(raw, list):
            raise ConfigError(f"{CONFIG_FILENAME}: [[override]] must be a list")
        out: list[Override] = []
        for index, block in enumerate(raw, start=1):
            where = f"{CONFIG_FILENAME} [[override]] #{index}"
            if not isinstance(block, dict):
                raise ConfigError(f"{where}: expected a table")
            _reject_unknown(where, block, OVERRIDE_KEYS)
            if "paths" not in block:
                raise ConfigError(
                    f"{where}: missing 'paths'. An override with no paths would "
                    f"apply everywhere, which is what the root tables are for."
                )
            paths = _as_str_tuple(f"{where}.paths", block["paths"])
            if not paths:
                raise ConfigError(f"{where}.paths: must not be empty")

            ruff_codes: tuple[str, ...] | None = None
            ruff_remove: frozenset[str] = frozenset()
            if (table := block.get("ruff")) is not None:
                _reject_unknown(f"{where} [ruff]", table, RUFF_OVERRIDE_KEYS)
                if "codes" in table and "remove" in table:
                    raise ConfigError(
                        f"{where} [ruff]: set either 'codes' (replace the "
                        f"inherited list) or 'remove' (subtract from it), not "
                        f"both — the result of combining them is a guess."
                    )
                if "codes" in table:
                    ruff_codes = _as_str_tuple(f"{where} [ruff].codes", table["codes"])
                if "remove" in table:
                    ruff_remove = frozenset(
                        _as_str_tuple(f"{where} [ruff].remove", table["remove"])
                    )

            semgrep_disabled: frozenset[str] = frozenset()
            if (table := block.get("semgrep")) is not None:
                _reject_unknown(f"{where} [semgrep]", table, SEMGREP_OVERRIDE_KEYS)
                if "disabled" in table:
                    semgrep_disabled = frozenset(
                        _as_str_tuple(f"{where} [semgrep].disabled", table["disabled"])
                    )

            banned_api: dict[str, str] | None = None
            if (table := block.get("banned_api")) is not None:
                banned_api = dict(table)

            latest: bool | None = None
            if (table := block.get("free_gates")) is not None:
                _reject_unknown(f"{where} [free_gates]", table, FREE_OVERRIDE_KEYS)
                if "latest_image_tag" in table:
                    latest = _as_bool(
                        f"{where} [free_gates].latest_image_tag",
                        table["latest_image_tag"],
                    )

            out.append(
                Override(
                    index=index,
                    paths=paths,
                    ruff_codes=ruff_codes,
                    ruff_remove=ruff_remove,
                    semgrep_disabled=semgrep_disabled,
                    banned_api=banned_api,
                    latest_image_tag=latest,
                )
            )
        return tuple(out)


def _split_codes(raw: str) -> tuple[str, ...]:
    return tuple(c.strip() for c in raw.split(",") if c.strip())


def _parse_banned_pairs(raw: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for item in raw.split(","):
        if ":" not in item:
            continue
        module, wrapper = item.split(":", 1)
        if module.strip():
            pairs[module.strip()] = wrapper.strip()
    return pairs
