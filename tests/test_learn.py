"""What `learn` is allowed to conclude, and what it must only suggest.

The behavioural contract is narrow and it is the whole value of the command:
a rule the tool cannot justify from something it read is emitted commented
out with its evidence, and a code the repository explicitly ignores is never
proposed at all.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from ratchet_gates.config import ConfigLoader
from ratchet_gates.learn.render import render_toml
from ratchet_gates.learn.service import LearnService
from ratchet_gates.learn.types import Confidence, SignalKind


def learn(repo: Path):
    return LearnService().learn(repo)


def test_never_re_enables_a_code_the_repo_explicitly_ignores(tmp_path: Path):
    """An explicit ignore is a standing decision, not an oversight.

    Re-enabling one is the documented route to a wall of false positives and
    a gate everybody routes around.
    """
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff.lint]\nselect = ["E"]\nignore = ["PLC0415", "UP"]\n'
    )
    rendered = render_toml(learn(tmp_path))
    enabled = tomllib.loads(rendered)["ruff"]["codes"]
    assert "PLC0415" not in enabled
    assert "UP" not in enabled
    assert "TRY400" in enabled  # not ignored, so still proposed
    assert "learn never re-enables an ignore" in rendered


def test_prose_only_conventions_are_suggested_not_enabled(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text(
        "# Conventions\n\n- All imports must be at the top of the file.\n"
        "- Push logic into a service class, not bare functions.\n"
    )
    result = learn(tmp_path)
    suggested = result.of(SignalKind.RUFF_CODE, Confidence.SUGGESTED)
    assert any(s.key == "PLC0415" for s in suggested)
    assert any("AGENTS.md:3" in s.evidence for s in suggested)

    # A convention no deterministic rule decides is routed to the reviewer
    # prompt rather than invented as a gate.
    judgement = result.of(SignalKind.JUDGEMENT)
    assert any(s.key == "one owner per domain concept" for s in judgement)
    assert "reviewer-prompt.md" in render_toml(result)


def test_banned_api_is_enabled_only_when_the_module_is_named_for_the_sdk(
    tmp_path: Path,
):
    """A name match is evidence; "it imports it" is a guess.

    On a real repository the looser rule attributed redis to a rate limiter
    and sqlalchemy to a test file. Banning an import repo-wide on either
    would be a wall of false positives on the first day.
    """
    deps = tmp_path / "deps"
    deps.mkdir()
    (deps / "redis.py").write_text("import redis\n")          # named for it
    (deps / "rate_limit.py").write_text("import redis\n")      # merely uses it
    (deps / "azure.py").write_text("import httpx\n")           # no name match
    (deps / "db_retry_test.py").write_text("import sqlalchemy\n")  # a test

    rendered = render_toml(learn(tmp_path))
    parsed = tomllib.loads(rendered)

    assert parsed["banned_api"] == {"redis": "deps/redis.py"}
    assert "httpx" not in parsed["banned_api"]
    assert '#   httpx = "deps/azure.py"' in rendered
    # A test file is never the wrapper for anything.
    assert "sqlalchemy" not in rendered


def test_nested_semgrep_directories_are_not_both_proposed(tmp_path: Path):
    """Listing .semgrep and .semgrep/rules loads every rule twice."""
    rules = tmp_path / ".semgrep" / "rules"
    rules.mkdir(parents=True)
    (rules / "a.yaml").write_text("rules: []\n")
    parsed = tomllib.loads(render_toml(learn(tmp_path)))
    assert parsed["semgrep"]["extra_rule_dirs"] == [".semgrep"]


def test_free_gates_follow_what_the_repo_actually_has(tmp_path: Path):
    (tmp_path / "alembic").mkdir()
    parsed = tomllib.loads(render_toml(learn(tmp_path)))
    assert parsed["free_gates"]["alembic_single_head"] is True
    assert parsed["free_gates"]["latest_image_tag"] is False


def test_output_is_valid_toml_the_loader_accepts(tmp_path: Path):
    """A learned config that the gate then rejects would be worse than none."""
    (tmp_path / "pyproject.toml").write_text('[tool.ruff]\nignore = ["UP"]\n')
    (tmp_path / "AGENTS.md").write_text("Use logger.exception in except blocks.\n")
    (tmp_path / "deps").mkdir()
    (tmp_path / "deps" / "redis.py").write_text("import redis\n")

    rendered = render_toml(learn(tmp_path))
    tomllib.loads(rendered)

    (tmp_path / ".ratchet-gates.toml").write_text(rendered)
    config = ConfigLoader(tmp_path).load(env={})
    assert "UP" not in config.root.ruff.codes
    assert config.root.banned_api["redis"] == "deps/redis.py"
