# ratchet-gates for coding agents

This tool is the deterministic half of "instructions suggest; gates enforce."
If you are an agent working in a repository that uses it, your job is to run it
**before you claim a task is done**, and to treat its verdict as ground truth
for the rules it covers.

## 1. Pre-push self-check — the part you control

```bash
git clone https://github.com/andrewlau624/ratchet-gates.git
cd ratchet-gates && make install
.venv/bin/ratchet-gates --repo /path/to/your/repo
```

Install from a clone, not `pip install git+https://…`: `rules/` is not packaged
into the distribution, so a wheel install reports `no bundled semgrep rules` and
passes that gate silently. The Action is unaffected.

Exit `0` means mergeable. Exit `2` means **new** violations you introduced and
must fix. Exit `3` means a gate tool is missing or crashed — that is a failure,
not a pass, and it is not something to work around.

Do not mark a task complete while the gate fails. A failing gate is not a
suggestion; it is the same class of defect the pull request is about to be
reviewed for, found twenty minutes earlier than CI would find it.

Put this in the host repo's `AGENTS.md` / `CLAUDE.md`:

> Before opening a PR, run `ratchet-gates --repo .`. Exit 0 means mergeable.
> Exit 2 means new violations you must fix. Do not report the task complete
> while the gate fails.

## 2. CI gate — the part that does not depend on you

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
          fetch-depth: 0
      - uses: andrewlau624/ratchet-gates@v1
```

With the `gates` check marked required in branch protection, every agent —
and every human — physically cannot merge a pull request carrying new
violations. That is a property of the repository, not a property of anyone's
diligence.

Both layers exist for different reasons. Pre-push is latency: the fix takes
thirty seconds instead of a CI round trip. The required check is the actual
gate: it cannot be skipped, does not depend on memory, and cannot be loosened
by whoever wrote the code.

## Why advice alone does not work

The audit behind these rules measured it. Function-local imports recurred on
**320 distinct pull requests** while the rule was written in the repository's
agent instructions, configured as a review-bot rule, **and** present as a
semgrep target. Three advisory layers, zero blocking ones, no change in
behaviour. The required check is the missing fourth layer.

## Configuring for your repo

| Setting | Env var | Example |
|---|---|---|
| Ruff code set (replaces the default) | `RATCHET_GATES_RUFF_CODES` | `PLC0415,TRY400,UP,ASYNC` |
| Banned-API table | `RATCHET_GATES_BANNED_APIS` | `boto3:deps/aws.py,redis:deps/redis.py` |

The gate uses the repo's **native ruff config** and adds codes via
`extend-select`, so the existing baseline (ignores, per-file ignores,
exclusions) is preserved. New rules are added; nothing is revoked. Findings are
scoped to **changed lines only**, so legacy violations never block adoption.

## The half this tool does not cover

Running the gate green is necessary, not sufficient. Of the thirteen structural
failure modes in the audit, four are deterministic and gated here; five are
permanently not machine-checkable — whether a hop earns its keep, which concept
owns a module, how many entrypoints a domain should have.

If you are reviewing rather than writing, use
[`rules/reviewer-prompt.md`](rules/reviewer-prompt.md). Two of its rules apply
to you directly as an author:

- **Do not raise findings the gate already decides.** If `PLC0415` is in the
  diff and the gate passed, that is a gate defect worth reporting — not a
  review comment worth writing.
- **"Out of scope" is only valid for code that is not new in this branch.**
  Check with `git log baseRef..HEAD -- <path>` before you say it. In the audit,
  roughly five of thirty scope-deferral claims were later reversed by the
  authors themselves once they checked provenance.
