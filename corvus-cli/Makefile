# corvus-cli dev harness — the Build > Test > Fix cycle, one command per step.
# Every target is idempotent and fresh-clone safe; run from this directory (make -C corvus-cli ...).

PYTHON ?= python3.12
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
RUFF := $(VENV)/bin/ruff

.PHONY: setup build lint test fix cycle clean

setup:  ## Create the 3.12 venv, install the deps and the pinned tooling
	@test -d $(VENV) || $(PYTHON) -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -e .
	$(PIP) install --quiet ruff==0.17.1 pytest pytest-cov
	@echo "setup: ok"

build: setup  ## Editable install + proof the entrypoint dispatches
	$(PIP) install --quiet -e .
	$(PIP) check  # the resolved dependency set must be internally consistent
	$(PY) -c "import corvus_cli.main as m; assert m.app is not None; print('import: ok')"
	$(VENV)/bin/corvus --help > /dev/null
	$(VENV)/bin/corvus check-target --help > /dev/null
	@echo "build: ok"

lint:  ## Ruff over the package and the tests
	$(RUFF) check src/ tests/
	@echo "lint: ok"

test:  ## The tests with coverage + junit evidence
	$(PY) -m pytest tests/ -q --cov=corvus_cli --cov-report=term \
		--cov-report=json:coverage.json --junitxml=junit.xml
	@echo "test: ok"

fix:  ## Apply the ruff autofixes (no `ruff format` — the repo does not use it)
	$(RUFF) check --fix src/ tests/
	@echo "fix: ok"

cycle: build lint test  ## The one command: build, lint, test

# clean removes only artifacts this harness generates (venv, caches, reports); nothing tracked
# or hand-written is in that list. PREFLIGHT:rollback-written — the rollback is `make setup && make cycle`.
clean:  ## Drop the venv and the test artifacts
	rm -rf $(VENV) .pytest_cache .ruff_cache src/corvus_cli/__pycache__ tests/__pycache__
	rm -f .coverage coverage.json junit.xml
	@echo "clean: ok"
