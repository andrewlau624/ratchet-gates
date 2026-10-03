"""Regenerate rules/semgrep/bundle.yml from the individual rule files.

The bundle is a convenience artifact for anyone wiring these rules into their
own semgrep setup. The gate does NOT load it — it reads rules/semgrep/rules/
directly, because loading both directories registers every rule twice. Keeping
the bundle generated rather than hand-edited is what stops the two from
disagreeing about what the rules say.
"""

from __future__ import annotations

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RULES_DIR = REPO_ROOT / "rules" / "semgrep" / "rules"
BUNDLE = REPO_ROOT / "rules" / "semgrep" / "bundle.yml"

HEADER = """\
# GENERATED FILE — do not edit.
#
# Consolidated from rules/semgrep/rules/*.yaml by `make bundle`.
# Edit the individual rule files and regenerate.
#
# The gate does not load this file; it reads rules/semgrep/rules/ directly.
# This bundle exists for consumers wiring the rules into their own semgrep
# setup with a single --config argument.
"""


def main() -> None:
    merged: list[dict] = []
    for path in sorted(RULES_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text())
        merged.extend(doc["rules"])
    BUNDLE.write_text(
        HEADER + yaml.safe_dump({"rules": merged}, sort_keys=False, width=100)
    )
    print(f"wrote {BUNDLE.relative_to(REPO_ROOT)} ({len(merged)} rules)")


if __name__ == "__main__":
    main()
