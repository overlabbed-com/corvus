# corvus-sdk dev harness — the build > lint > test loop, one command per step.
# python3.12 is PINNED: bare python3 on this host is 3.15 and breaks parity with CI.

PYTHON ?= python3.12
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
RUFF := $(VENV)/bin/ruff

.PHONY: setup build lint test fix cycle clean

setup:  ## Bootstrap the 3.12 venv, the component deps and the pinned tooling
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -e ".[dev]"
	$(PIP) install --quiet ruff==0.17.1 pytest pytest-cov
	@echo "setup: ok"

build:  ## The editable install plus a real import + client/model proof
	$(PIP) install --quiet -e .
	$(PIP) check  # the resolved dependency set must be internally consistent
	$(PY) -c 'import corvus_sdk as s; c = s.CorvusClient("http://corvus:8000/", token="t"); assert c._base_url == "http://corvus:8000", c._base_url; assert s.Event("E-1", "t0", "src", "change.completed", "tg").data == {}; assert issubclass(s.CorvusError, Exception); print("build: ok —", s.__version__)'
	@echo "build: ok"

lint:  ## Ruff over the package and the tests
	$(RUFF) check src/ tests/
	@echo "lint: ok"

test:  ## The tests with the coverage measurement
	$(PY) -m pytest tests/ -q --cov=corvus_sdk --cov-report=term --cov-report=json:coverage.json --junitxml=junit.xml
	@echo "test: ok"

fix:  ## Apply the auto-fixable lint findings
	$(RUFF) check --fix src/ tests/
	@echo "fix: ok"

cycle: build lint test  ## THE one command: build > lint > test

# clean only touches artifacts this harness created: the venv and the test reports.
# PREFLIGHT:rollback-written — the rollback is `make setup` (and `make test`), which
# recreates every deleted artifact from pyproject.toml in one command.
clean:  ## The venv and the test artifacts (recoverable: make setup + make test)
	rm -rf $(VENV) .coverage coverage.json junit.xml .pytest_cache .ruff_cache
	@echo "clean: ok"
