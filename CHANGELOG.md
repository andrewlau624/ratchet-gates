# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The floating `v1` tag always points at the newest `v1.x.y` release, so
`uses: andrewlau624/ratchet-gates@v1` tracks compatible updates.

## [Unreleased]

## [0.1.0] — 2026-10-03

First release. Self-check green; not yet running in a production repository's
CI.

### Added
- **Ratcheted gate CLI** (`ratchet-gates`). Findings are filtered to the lines
  the pull request added, measured against the merge-base with the default
  branch. Legacy violations never block adoption and no suppression sweep is
  needed.
- **Four gates**: `ruff-diff` (the repo's native config plus codes added via
  `lint.extend-select`, so nothing the repo already ignores is revoked),
  `semgrep-baseline` (10 custom rules behind `--baseline-commit`), `banned-api`
  (opt-in via `RATCHET_GATES_BANNED_APIS`), and free gates (`:latest` image
  tags, alembic single-head).
- **Composite GitHub Action** (`action.yml`), adopted with one workflow line.
  Publishes `result` (`CLEAN` / `NEW_VIOLATIONS` / `TOOLING_FAILURE`) and
  `summary` outputs.
- **`--self-check`**: ratchet semantics in isolated git repositories plus
  `semgrep --test` over every rule's fixtures. A rule that silently matches
  nothing is indistinguishable from compliance, so fixtures are mandatory.
- **`make bundle`** regenerates `rules/semgrep/bundle.yml` from the individual
  rule files, so the single-file copy cannot drift from the source of truth.
- **`rules/reviewer-prompt.md`**: the evidence-backed reviewer contract for the
  judgment layer that cannot be gated deterministically.
- Exit codes: `0` clean, `2` new violations, `3` tooling failure. A gate tool
  that cannot run is a failure, not a pass.

[Unreleased]: https://github.com/andrewlau624/ratchet-gates/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/andrewlau624/ratchet-gates/releases/tag/v0.1.0
