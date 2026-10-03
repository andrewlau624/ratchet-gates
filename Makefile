.PHONY: install self-check test semgrep-test

install: ## Install into the local venv
	python3 -m venv .venv
	.venv/bin/pip install -e .

self-check: ## Run the tool's own gate suite (pytest + semgrep fixtures)
	.venv/bin/python -m ratchet_gates --self-check

test: ## pytest gate tests
	.venv/bin/python -m pytest tests/ -q

semgrep-test: ## semgrep rule fixtures
	.venv/bin/semgrep --test --config rules/semgrep/rules/ rules/semgrep/targets/
bundle: ## Regenerate the consolidated rule bundle from rules/semgrep/rules/
	.venv/bin/python scripts/build_bundle.py
