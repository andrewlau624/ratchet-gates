# Configuration reference

The gate's policy is data. `ratchet-gates` ships one organisation's rules as a
starting point; `.ratchet-gates.toml` is how you replace them with yours, and
`ratchet-gates learn` is how you derive that file from your own repository
instead of hand-writing it.

With no config file present the tool behaves exactly as it does out of the box.
Adding one is opt-in, and nothing in it is required.

## Where the policy comes from

Six layers, lowest priority first:

| | Layer | Set by |
|---|---|---|
| 1 | built-in `default` profile | shipped with the tool |
| 2 | named profile | `profile = "minimal"`, or `--profile` |
| 3 | root tables | `.ratchet-gates.toml` |
| 4 | matching `[[override]]` blocks | `.ratchet-gates.toml`, by path |
| 5 | environment | `RATCHET_GATES_*` |
| 6 | command line | `--ruff-codes`, `--semgrep-severity` |

Overrides sit below the environment and the command line on purpose: they
refine the repository's own policy, while a flag is a deliberate one-off that
outranks the whole file.

Run `ratchet-gates config --path some/file.py` to print the resolved policy for
any path, along with the chain of layers that produced it. Every gate run
prints the same chain on its first line.

## Root tables

```toml
profile = "default"          # which shipped profile to start from

[ruff]
# Added to your OWN ruff config via lint.extend-select. Your existing ignores,
# per-file-ignores and exclusions all survive — codes are added, never revoked.
codes = ["PLC0415", "TRY400", "UP", "TID251", "ASYNC", "RUF006", "RUF100", "PGH003", "PGH004"]

[semgrep]
severity        = "ERROR"    # or "WARNING" to run advisory first
bundled_rules   = true       # the 10 rules shipped with the tool
extra_rule_dirs = [".semgrep"]   # your own, repo-relative
disabled        = ["ratchet-skip-without-ticket"]

[banned_api]
# module = "the wrapper that should be imported instead"
redis = "deps/redis.py"

[free_gates]
latest_image_tag    = true
alembic_single_head = true   # repo-global, see below
```

Do not list a directory in `extra_rule_dirs` that contains another one you have
also listed. semgrep reads a `--config` directory recursively, so the nested
rules load twice and every finding is reported twice.

## Override blocks

```toml
[[override]]
paths = ["tests/**", "**/*_test.py"]
ruff  = { remove = ["TID251"] }

[[override]]
paths = ["vendored/**"]
ruff       = { codes = ["F"] }        # replace, rather than subtract
semgrep    = { disabled = ["ratchet-mock-patch-without-autospec"] }
free_gates = { latest_image_tag = false }
```

**All matching blocks apply, in declaration order; later blocks win.** Order is
the rule rather than a most-specific-pattern heuristic, because "which of these
two globs is more specific" is a question readers and implementations answer
differently.

An override's `ruff` table takes either `codes` (replace the inherited list) or
`remove` (subtract from it), never both — combining them has no obvious meaning,
so the tool refuses rather than picking one.

`alembic_single_head` is **repo-global** and cannot appear in an override. A
migration graph is a property of the repository, with no single path to
attribute it to. Putting it in an override is an error rather than a line that
is silently ignored.

### Glob syntax

| Pattern | Matches |
|---|---|
| `**/` | zero or more leading directories |
| `**` | anything, including `/` |
| `*` | anything except `/` |
| `?` | one character except `/` |
| `dir/` | shorthand for `dir/**` |

`*_test.py` matches only a top-level file; write `**/*_test.py` for the whole
tree. (`ratchet-gates learn` applies that translation automatically when it
reads ruff's basename-matched `per-file-ignores`.)

## What the tool refuses

Each of these aborts the run with exit 3 rather than resolving to something
plausible:

- an unknown key, reported with the nearest valid one
- a repo-global key inside an `[[override]]`
- `codes` and `remove` in the same override
- an `[[override]]` with no `paths`
- a severity that is not `ERROR` or `WARNING`
- a profile name that does not exist
- **a policy that enables no gates at all**

The last one is the reason for all the others. A run that checks nothing exits
0 for exactly the same reason a clean run does, so a typo that silently
disables a gate is indistinguishable from compliance — the defect class this
tool exists to remove, and one it has shipped twice.

## Environment variables

| Variable | Effect |
|---|---|
| `RATCHET_GATES_RUFF_CODES` | comma-separated; replaces the code set |
| `RATCHET_GATES_BANNED_APIS` | `module:wrapper` pairs, comma-separated |

A variable that is exported but blank counts as unset. Treating it as "select
nothing" is what silently disabled every rule in v0.1.0.

## `ratchet-gates learn`

```bash
ratchet-gates learn --repo .                      # print to stdout
ratchet-gates learn --repo . --out .ratchet-gates.toml
ratchet-gates learn --repo . --from-history       # also mine merged PRs
```

Four static inspectors read your ruff config, your directory layout, any
semgrep rules you already maintain, and your `AGENTS.md` / `CLAUDE.md` /
`CONTRIBUTING.md`. `--from-history` adds a pass over merged pull requests,
clustering recurring review comments; it needs `gh` authenticated or
`GITHUB_TOKEN` set, and takes minutes rather than seconds.

Two rules govern the output, and they are the point of the command:

**A code your ruff config explicitly ignores is never proposed.** An ignore is
a standing decision. Re-enabling one produces a wall of false positives and a
gate everybody routes around.

**Anything inferred rather than read is written commented out, with its
evidence.** Prose in a contributing guide states an intention; it does not
establish that a particular lint code is the right way to enforce it. A wrapper
module that merely imports an SDK is not necessarily the wrapper *for* that SDK
— on a real repository the looser rule attributed redis to a rate limiter and
sqlalchemy to a test file. Enabling either on a guess is the wall of false
positives again, so `learn` hands you the evidence and lets you decide.

`learn` will not overwrite an existing config. Write to a new path and diff.

## What configuration cannot reach

Of the thirteen structural failure modes in the audit these rules came from,
four are deterministic, four are heuristic, and five are not machine-checkable
at any useful precision — whether a hop earns its keep, which concept owns a
module, how many entrypoints a domain should have.

No profile covers those, and `learn` deliberately does not invent rules for
them. When it finds one written down in your repo it says so and points at
[`../rules/reviewer-prompt.md`](../rules/reviewer-prompt.md), which is the
contract for the layer a gate cannot reach.
