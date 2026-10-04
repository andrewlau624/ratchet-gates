"""Config resolution: precedence, scoping, and what it refuses.

The rejection tests carry most of the weight. Every one of them covers a way
a config could otherwise resolve to "no gate ran" while the run reported
success, which is the defect class this project exists to remove and which it
has now shipped twice.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ratchet_gates.config import ConfigLoader
from ratchet_gates.config.globs import matches
from ratchet_gates.types import ConfigError

ZERO_GATES = """
[ruff]
codes = []
[semgrep]
bundled_rules = false
extra_rule_dirs = []
[banned_api]
[free_gates]
latest_image_tag = false
alembic_single_head = false
"""


def load(tmp_path: Path, toml: str | None = None, **kwargs):
    if toml is not None:
        (tmp_path / ".ratchet-gates.toml").write_text(toml)
    kwargs.setdefault("env", {})
    return ConfigLoader(tmp_path).load(**kwargs)


def test_no_config_file_uses_the_builtin_default(tmp_path: Path):
    """Zero-config adoption must not regress: one workflow line, no file."""
    config = load(tmp_path)
    assert "PLC0415" in config.root.ruff.codes
    assert config.root.semgrep.bundled_rules is True
    assert config.root.free_gates.alembic_single_head is True


def test_named_profile_switches_the_whole_policy(tmp_path: Path):
    config = load(tmp_path, 'profile = "minimal"')
    assert config.root.semgrep.bundled_rules is False
    assert config.root.free_gates.latest_image_tag is False
    assert "PLC0415" in config.root.ruff.codes


@pytest.mark.parametrize(
    "toml,env,cli,expected",
    [
        ('[ruff]\ncodes = ["A"]', {}, None, ("A",)),
        ('[ruff]\ncodes = ["A"]', {"RATCHET_GATES_RUFF_CODES": "B"}, None, ("B",)),
        ('[ruff]\ncodes = ["A"]', {"RATCHET_GATES_RUFF_CODES": "B"}, "C", ("C",)),
        # A set-but-blank variable means "unset", not "select nothing".
        ('[ruff]\ncodes = ["A"]', {"RATCHET_GATES_RUFF_CODES": "   "}, None, ("A",)),
    ],
)
def test_precedence_cli_beats_env_beats_file(tmp_path, toml, env, cli, expected):
    config = load(tmp_path, toml, env=env, cli_ruff_codes=cli)
    assert config.root.ruff.codes == expected


def test_overrides_apply_in_declaration_order(tmp_path: Path):
    config = load(
        tmp_path,
        """
[[override]]
paths = ["tests/**"]
ruff = { remove = ["TID251"] }

[[override]]
paths = ["tests/legacy/**"]
ruff = { codes = ["F"] }
""",
    )
    assert "TID251" in config.for_path("src/a.py").ruff.codes
    assert "TID251" not in config.for_path("tests/a.py").ruff.codes
    assert config.for_path("tests/legacy/a.py").ruff.codes == ("F",)


def test_provenance_names_every_layer_that_applied(tmp_path: Path):
    """The log has to answer "which policy ran" without a directory walk."""
    config = load(tmp_path, '[[override]]\npaths = ["x/**"]\nruff = { codes = ["F"] }')
    assert config.for_path("x/a.py").source == (
        "profile 'default'",
        ".ratchet-gates.toml",
        "override #1 (x/**)",
    )


@pytest.mark.parametrize(
    "toml,fragment",
    [
        ("ruf = {}", "unknown key 'ruf'"),
        ('[ruff]\ncode = ["F"]', "Did you mean 'codes'"),
        ('[semgrep]\nseverity = "LOUD"', "not one of ERROR, WARNING"),
        ('profile = "nope"', "unknown profile"),
        ('[[override]]\nruff = { remove = ["F"] }', "missing 'paths'"),
        ('[[override]]\npaths = []', "must not be empty"),
        (
            '[[override]]\npaths = ["t/**"]\nruff = { codes = ["F"], remove = ["E"] }',
            "not both",
        ),
        (
            '[[override]]\npaths = ["t/**"]\nfree_gates = { alembic_single_head = false }',
            "repo-global",
        ),
        (ZERO_GATES, "enables no gates"),
    ],
)
def test_refuses_rather_than_guesses(tmp_path: Path, toml: str, fragment: str):
    with pytest.raises(ConfigError, match=fragment):
        load(tmp_path, toml)


@pytest.mark.parametrize(
    "pattern,path,expected",
    [
        ("tests/**", "tests/a.py", True),
        ("tests/**", "tests/deep/a.py", True),
        ("tests/**", "mytests/a.py", False),
        ("**/*_test.py", "a/b/c_test.py", True),
        ("*.py", "a/b.py", False),
        ("alembic/", "alembic/versions/1.py", True),
    ],
)
def test_glob_semantics_match_the_documented_behaviour(pattern, path, expected):
    assert matches(pattern, path) is expected
