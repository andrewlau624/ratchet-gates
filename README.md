# ratchet-gates

Deterministic code-quality gates that fail **only on violations your pull
request introduced**.

Findings are filtered to the lines the diff added, measured against the
merge-base with the default branch. A repository with ten thousand legacy
violations adopts this in one commit and the gate is green on day one — no
`noqa` sweep, no baseline file to maintain, and no "we'll clean it up first"
phase that never arrives.

That property is the whole design. Everything else serves it.

```yaml
- uses: andrewlau624/ratchet-gates@v1
```

## Why a ratchet

The usual way to adopt a linter in an old codebase is to fix everything first,
or suppress everything first. Both fail. The first never finishes. The second
produces a repository where suppression is the norm and the gate is decoration.

Diff scoping removes the choice. `_added_lines()` parses
`git diff --unified=0 BASE...HEAD`, keeps the line numbers the branch added, and
discards findings anywhere else before computing the verdict. The baseline is a
**commit**, not a checked-in file — so it cannot drift, and a pull request
cannot raise its own ceiling by editing it.

## What it runs

| Gate | What it checks | Scoping |
|---|---|---|
| `ruff-diff` | Your **own** ruff config, plus extra codes added via `lint.extend-select` | Lines the diff added |
| `semgrep-baseline` | 10 custom rules, each with a passing fixture | `--baseline-commit` |
| `banned-api` | Direct imports of wrapped SDKs outside their canonical module | Changed files; **opt-in** |
| `free-gates` | `:latest` image tags, alembic multi-head | Changed files |

The ruff gate **extends**, it does not replace. Your existing ignores,
per-file-ignores, and exclusions are all preserved; codes are added and nothing
is revoked. This matters more than it sounds: re-enabling a code a repository
already deliberately ignores produces a wall of false positives, and a gate that
produces a wall of false positives gets routed around within a week.

### The rules are a starter set, not a standard

The bundled rules came from a review audit of 8,563 pull requests across 23
repositories, so they encode one organisation's recurring defects. Yours differ.
Every rule is replaceable:

- Swap the ruff code set with the `ruff-codes` input.
- Add, edit, or delete files in `rules/semgrep/rules/` — each needs a fixture in
  `rules/semgrep/targets/`, which `make self-check` enforces.
- Point `RATCHET_GATES_BANNED_APIS` at your own wrapper layout.

The engine does not care what the rules say. It cares that each one has a
fixture proving it still matches, and that findings are scoped to added lines.

## Install

One job, in `.github/workflows/gates.yml`:

```yaml
name: gates
on: [pull_request]

jobs:
  gates:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0        # required: the ratchet needs the merge-base
      - uses: andrewlau624/ratchet-gates@v1
```

Then mark the `gates` check **required** in your branch ruleset.

Without that second step this is a notification, not a gate — and the
distinction is the entire point. In the audit this came from, function-local
imports recurred on **320 distinct pull requests** while the rule was
simultaneously written in the repo's agent instructions, configured in the
review bot, and present as a semgrep target. Three advisory layers, zero
blocking ones. Advice does not survive contact with anyone in a hurry; a
required check does.

`fetch-depth: 0` is not optional. A shallow clone has no merge-base, and tools
that cannot find one report "no new findings" and pass — a green check that
measured nothing.

## Configuration

Action inputs:

| Input | Default | Effect |
|---|---|---|
| `base` | merge-base with the default branch | Override the ratchet baseline. Needed only for unusual branch topology. |
| `ruff-codes` | the bundled set | **Replaces** the bundled code set entirely. |
| `semgrep-severity` | `ERROR` | Set to `WARNING` to run advisory first. |

Environment variables, settable at the job level:

| Variable | Default | Effect |
|---|---|---|
| `RATCHET_GATES_RUFF_CODES` | `PLC0415,TRY400,UP,TID251,ASYNC,RUF006,RUF100,PGH003,PGH004` | Same as the `ruff-codes` input. |
| `RATCHET_GATES_BANNED_APIS` | empty — gate off | Comma-separated `module:canonical_path` pairs. |

```yaml
      - uses: andrewlau624/ratchet-gates@v1
        env:
          RATCHET_GATES_BANNED_APIS: boto3:deps/aws.py,redis:deps/redis.py
```

`banned-api` is opt-in because wrapper layout is project-specific. It turns
"someone wrote a second S3 client" from a thing a reviewer has to notice into a
thing CI refuses. Ruff's `TID251` covers the same class declaratively if you
prefer to configure it there.

## Rolling it out

Ship at `semgrep-severity: WARNING` for two weeks, collect the exception set,
then promote to `ERROR` and mark the check required.

Watch the suppression rate (`noqa`, `nosemgrep`, `eslint-disable`) while you do.
**A step change in suppressions the week a gate lands means the gate was muted,
not met.** 20% is a reasonable line at which to investigate.

If one rule's false-positive rate exceeds ~10%, delete it rather than argue with
it. That is Google Tricorder's published operating number, above which an
analyzer gets disabled by its users whether or not its author agrees.

## CLI

```bash
pip install git+https://github.com/andrewlau624/ratchet-gates.git

ratchet-gates --repo .                      # run the gates here
ratchet-gates --self-check                  # run the tool's own test suite
ratchet-gates --repo . --semgrep-severity WARNING
```

| Exit code | Meaning |
|---|---|
| `0` | Clean — no new violations on added lines |
| `2` | New violations |
| `3` | Tooling failure — a required tool is missing or crashed |

Exit `3` is deliberately distinct from `0`. A gate tool that cannot run is a
failure, not a pass; the opposite convention is how a green check comes to mean
nothing.

Coding agents should run `ratchet-gates --repo .` before claiming a task is
done — the same verdict CI will produce, twenty minutes earlier. See
[AGENTS.md](AGENTS.md).

## Self-check

```bash
make install
make self-check
```

Two suites, both required:

1. **pytest** — ratchet semantics in throwaway git repositories: a new violation
   exits 2, the same violation already on `origin/main` exits 0, a clean branch
   exits 0.
2. **`semgrep --test`** — every custom rule matches its fixture.

The second exists because **a rule that silently matches nothing looks exactly
like compliance.** Writing these fixtures caught three real defects in the
drafted rules: a negative-lookahead regex the Rust engine cannot compile (so it
could never have matched), a two-regex `AND` whose halves could not both hold,
and a list-marker form (`- uses:`) the pattern missed. If you change a rule,
change its fixture — `make self-check` will not let you forget.

`make bundle` regenerates `rules/semgrep/bundle.yml`, a single-file copy for
consumers wiring these rules into their own semgrep setup. The gate does not
load it; it reads `rules/semgrep/rules/` directly, which is also what the
fixtures test.

## What this does not fix

Deliberately, and this is the honest part.

The audit behind these rules classified thirteen distinct control-flow and
placement failure modes. **Four are deterministic** and are gated here or by
`import-linter`. **Four are heuristic.** **Five are permanently un-gateable** —
whether a hop earns its keep, which concept owns a module, how many entrypoints
a domain should have — and they include the single most recurrent human review
finding in the corpus.

"Thin entrypoints" is roughly **40% machine-checkable**. No amount of
rule-writing moves that number, because the rest requires a model of the domain.
The clearest evidence: the same reviewer files "make this a service class" and
"no need for separate service classes", sometimes in the same pull request. Both
are correct. The invariant is *one owner per domain concept*, which is a
statement about the domain, not the syntax.

That layer belongs to humans and to LLM review, and
[`rules/reviewer-prompt.md`](rules/reviewer-prompt.md) is the contract for it:
fresh-context review of the diff only, every finding carries evidence (your own
rule file, a traced code path, or the sibling that already implements it, with
`file:line`), and **dismissing a finding requires attaching evidence, not an
argument**. It is advisory by design and does not belong in CI.

Also out of scope: this tool does not measure whether any of it worked. Every
gate here is pre-merge. Revert rate, recurrence per finding-class, and
suppression rate are what tell you the gate changed something, and they live
outside this repository.

## Repository layout

```
src/ratchet_gates/cli.py              the four gates and the ratchet
action.yml                            composite GitHub Action
scripts/build_bundle.py               regenerates the consolidated rule bundle
rules/ruff.toml                       example ruff config (not a dependency)
rules/semgrep/rules/<id>.yaml         one file per custom rule — source of truth
rules/semgrep/targets/                one fixture per rule, run by semgrep --test
rules/semgrep/bundle.yml              generated single-file copy — not loaded by the gate
rules/reviewer-prompt.md              the judgment layer CI cannot reach
tests/test_gates.py                   ratchet semantics in isolated git repos
```

Python 3.11+. Requires `ruff` and `semgrep` on PATH; the Action installs both.

## Status

Self-check green. Not yet running in a production repository's CI — if you adopt
it, start at `WARNING`. See [CHANGELOG.md](CHANGELOG.md).

## License

MIT. See [LICENSE](LICENSE).
