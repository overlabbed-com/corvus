# The corvus-v2 dev harness — the Build > Test > Fix cycle, one command per step.
# The engine is the deployed artifact (image corvus-v2:<sha>): its harness is the
# gate that decides whether a change is deployable. Every step is idempotent.

PYTHON ?= python3.12
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
RUFF := $(VENV)/bin/ruff
METRICS := ../docs/canonical-path/dev-metrics.json
SRC := corvus/ tests/

.PHONY: setup build lint test fix metrics metrics-check run check cycle clean mutation conformance

setup:  ## Bootstrap the venv + the deps (fresh-clone safe, pinned interpreter)
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -r requirements.txt
	$(PIP) install --quiet pytest pytest-cov ruff==0.17.1 httpx
	@echo "setup: ok ($$($(PY) --version))"

build:  ## The engine up + the live proof: health, an authenticated read, and the 401 control
	$(PIP) check  # the resolved dependency set must be internally consistent
	$(PY) scripts/dev_check.py

lint:  ## Ruff over the package and the tests
	$(RUFF) check $(SRC)
	@echo "lint: ok"

test:  ## The tests with the coverage measurement
	$(PY) -m pytest tests/ -q \
		--cov=corvus --cov-report=term --cov-report=json:coverage.json \
		--junitxml=junit.xml
	@echo "test: ok"

fix:  ## The autofix step — ruff repairs what it can, then lint proves it
	$(RUFF) check --fix $(SRC)
	@echo "fix: ok (run `make lint` to confirm)"

metrics:  ## Regenerate the dev-metrics artifact from the last test run
	$(PY) scripts/gen_metrics.py \
		--coverage coverage.json --junit junit.xml --out $(METRICS) \
		--source "$$(git rev-parse --short HEAD)" \
		--duration "$$($(PY) -c 'import xml.etree.ElementTree as ET; r=ET.parse("junit.xml").getroot(); s=r.find("testsuite") if r.tag=="testsuites" else r; print(round(float(s.get("time",0)),2))')"
	@echo "metrics: regenerated"

metrics-check:  ## The drift guard: the committed metrics must match a fresh run
	$(PY) scripts/gen_metrics.py \
		--coverage coverage.json --junit junit.xml --out /tmp/metrics-check.json \
		--source "$$(git rev-parse --short HEAD)"
	$(PY) scripts/check_metrics.py --expected $(METRICS) --actual /tmp/metrics-check.json

run: build  ## Alias: the live check is the build step

check: lint test metrics-check  ## The full gate set (what CI runs)

cycle: build lint test metrics-check  ## THE Build > Test > Fix loop, one command

mutation:  ## The mutation evidence (the phase-gate target)
	$(PY) -c "import sys; sys.path.insert(0, '.'); from corvus.conformance import run_mutation_suite; import json; r = run_mutation_suite(); print(json.dumps(r, indent=1)); exit(0 if r['all_mutants_caught'] else 1)"

conformance:  ## The conformance run against the engine shim (the phase-gate target)
	$(PY) -m corvus.engine_shim --port 8933 & sleep 2; \
	$(PY) -c "import sys; sys.path.insert(0, '.'); from corvus.conformance import conformance_run; import json; r = conformance_run('http://127.0.0.1:8933'); print(json.dumps(r, indent=1)); exit(0 if r['failed'] == 0 else 1)"; \
	pkill -f "engine_shim --port 8933" || true

# PREFLIGHT:rollback-written — clean deletes only REGENERABLE state (the venv and the
# pytest cache); `make setup` and `make test` recreate both. It deliberately does NOT
# delete coverage.json / junit.xml, which are tracked artifacts feeding dev-metrics.json.
clean:  ## The regenerable artifacts only (never the tracked metrics inputs)
	rm -rf $(VENV) .pytest_cache
	@echo "clean: ok — run `make setup` to rebuild"
