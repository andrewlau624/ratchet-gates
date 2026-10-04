# Changelog

All notable changes are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The floating `v1` tag always points at the newest `v1.x.y` release, so
`uses: andrewlau624/ratchet-gates@v1` tracks compatible updates.

## [Unreleased]

## [0.3.0] — 2026-10-04

Makes an advisory rollout observable. Previously a run told you about one
pull request and left no trace, which is enough to block on and not enough
to decide what to block on.

### Added
- **`--json-out PATH`** writes a machine-readable run record: verdict, the
  policy chain that produced it, and every finding with path, line, code and
  message.
- **`ratchet-gates report`** folds many records. Ranks what fires by *distinct
  runs* rather than raw count — twenty hits in one pull request is a refactor,
  one hit in twenty pull requests is a rule — and lists configured codes that
  have **never fired**, which is the set to delete before making the check
  required.
- **The action now reports where you already are**: a job summary on every
  run, one sticky pull-request comment updated in place (`comment: "false"`
  to opt out), and the run record uploaded as a 90-day artifact. All three
  render from the same record, so they cannot disagree with the log.

### Changed
- Findings are a structured `Finding(path, line, code, message)` instead of a
  preformatted string, so nothing has to parse the tool's own output back.

## [0.2.1] — 2026-10-04

See 0.2.0; this adds `--advisory` and corrects the rollout instructions.

## [0.2.0] — 2026-10-03

Conventions become data the tool carries rather than behaviour compiled into
it. The bundled rules were one organisation's; now they are a starting point
you can replace, derive, or switch between per directory.

### Added
- **`.ratchet-gates.toml`** — one file at the repo root configures the ruff
  code set, semgrep rule sources and severity, the banned-API table, and the
  free gates. With no file present the gate behaves exactly as in 0.1.0.
- **`[[override]]` blocks** scope policy to path globs for monorepos. All
  matching blocks apply in declaration order, later ones winning — order
  rather than a most-specific-pattern heuristic, because readers and
  implementations disagree about which of two globs is more specific.
- **`ratchet-gates learn`** derives a profile from a repository: its ruff
  config, directory layout, existing semgrep rules, and contributing docs.
  `--from-history` additionally mines merged pull requests for the conventions
  reviewers enforce in practice. A code the repo explicitly ignores is never
  proposed, and anything inferred rather than read is written commented out
  with its evidence.
- **Named profiles** (`default`, `minimal`) with `--profile` or
  `profile = "..."`, and `ratchet-gates profiles` to list them.
- **`ratchet-gates config --path <file>`** prints the policy for any path and
  the chain of layers that produced it. Every gate run prints the same chain.
- `docs/configuration.md`: full schema, glob syntax, and what the loader
  refuses.

### Changed
- `cli.py` is argparse and exit codes only. Gates, config resolution, the
  ratchet, and `learn` are separate subsystems; each gate is one file behind
  `GateService`.
- Gate outcomes are a `GateStatus` enum. `main()` previously decided tooling
  failure by matching `GateResult.detail` against three string literals, so
  rewording a message would have downgraded a tooling failure to a pass.
- A skipped gate now prints `[SKIP]` rather than `[PASS] … SKIPPED:`, and ruff
  findings are reported with repo-relative paths.
- The action invokes `python3 -m ratchet_gates` instead of running `cli.py` as
  a script, which the package-relative imports require.
- Exit codes are unchanged: `0` clean, `2` new violations, `3` tooling failure.

### Fixed
- **`--advisory`, because the documented soft-launch path disabled the gate.**
  The rollout advice was "ship at `semgrep-severity: WARNING` for two weeks".
  `--severity` is a rule filter: eight of the ten bundled rules declare
  `ERROR`, so `WARNING` stopped them reporting at all and the gate went green
  having checked almost nothing. `--advisory` runs every gate, reports every
  finding, and exits 0.
- **`added_lines` merged every file's line numbers into one set**, so a finding
  on line 12 of an untouched file counted as new whenever any file in the diff
  had added a line 12. Now keyed by file.
- **A missing bundled rules directory is a tooling failure, not an empty rule
  set.** `semgrep.bundled_rules` stays a declared intention all the way to the
  gate, so a wheel install that has no rules fails loudly instead of reporting
  a clean scan. Closes the silent pass in issue #1 (the packaging gap itself
  remains).

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

[Unreleased]: https://github.com/andrewlau624/ratchet-gates/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/andrewlau624/ratchet-gates/releases/tag/v0.3.0
[0.2.0]: https://github.com/andrewlau624/ratchet-gates/releases/tag/v0.2.0
[0.1.0]: https://github.com/andrewlau624/ratchet-gates/releases/tag/v0.1.0
