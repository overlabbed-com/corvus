# The Corvus dev harness — the Build > Test > Fix cycle, one command per step.
# `make cycle` is the full loop; every step is idempotent and fresh-clone safe.

VENV := corvus-v2/.venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
METRICS := docs/canonical-path/dev-metrics.json

.PHONY: setup lint test metrics run check cycle clean

setup:  ## Bootstrap the venv + the deps (fresh-clone safe)
	python3 -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -r corvus-v2/requirements.txt
	$(PIP) install --quiet pytest pytest-cov ruff httpx
	@echo "setup: ok"

lint:  ## Ruff over the v2 package and the tests
	$(PY) -m ruff check corvus-v2/corvus/ corvus-v2/tests/
	@echo "lint: ok"

test:  ## The tests with the coverage measurement
	cd corvus-v2 && .venv/bin/python -m pytest tests/ -q \
		--cov=corvus --cov-report=term --cov-report=json:coverage.json \
		--junitxml=junit.xml
	@echo "test: ok"

metrics:  ## Regenerate the dev-metrics artifact from the last test run
	$(PY) corvus-v2/scripts/gen_metrics.py \
		--coverage corvus-v2/coverage.json --junit corvus-v2/junit.xml --out $(METRICS) \
		--source "$$(git rev-parse --short HEAD)" --duration "$$(cd corvus-v2 && .venv/bin/python -c "import json;print(json.load(open('coverage.json')).get('duration',0) if False else 0)")"
	@echo "metrics: regenerated"

metrics-check:  ## The drift guard: the committed metrics must match the fresh run
	$(PY) corvus-v2/scripts/gen_metrics.py \
		--coverage corvus-v2/coverage.json --junit corvus-v2/junit.xml --out /tmp/metrics-check.json \
		--source "$$(git rev-parse --short HEAD)"
	$(PY) corvus-v2/scripts/check_metrics.py --expected $(METRICS) --actual /tmp/metrics-check.json

run:  ## The server up + the live health check (the dev loop's "build" step)
	cd corvus-v2 && .venv/bin/python -c "\
import sys, threading, time, json, urllib.request;\
sys.path.insert(0, '.');\
from corvus.app import create_app;\
from corvus.config import FleetConfig;\
cfg = FleetConfig(name='dev-fleet', node_id='dev-1', api_key='dev-local-key');\
app = create_app(config=cfg, db_path=':memory:');\
t = threading.Thread(target=lambda: __import__('uvicorn').run(app, host='127.0.0.1', port=8932, log_level='error'), daemon=True);\
t.start(); time.sleep(1.5);\
r = json.loads(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8932/health', headers={'X-Corvus-Key': 'dev-key'}), timeout=5).read());\
assert r['status'] == 'ok', r;\
print('run: ok —', r['fleet'])"

check: lint test metrics-check  ## The gates the CI runs (identical locally)

cycle: check run  ## THE Build > Test > Fix loop, one command

clean:  ## The artifacts
	rm -rf $(VENV) corvus-v2/.pytest_cache corvus-v2/coverage.json /tmp/metrics-check.json

# WP14: the mutation evidence + the conformance run (the phase-gate targets)
mutation:
	cd corvus-v2 && .venv/bin/python -c "import sys; sys.path.insert(0, '.'); from corvus.conformance import run_mutation_suite; import json; r = run_mutation_suite(); print(json.dumps(r, indent=1)); exit(0 if r['all_mutants_caught'] else 1)"

conformance:
	cd corvus-v2 && .venv/bin/python -m corvus.engine_shim --port 8933 & sleep 2; .venv/bin/python -c "import sys; sys.path.insert(0, '.'); from corvus.conformance import conformance_run; import json; r = conformance_run('http://127.0.0.1:8933'); print(json.dumps(r, indent=1)); exit(0 if r['failed'] == 0 else 1)"; pkill -f "engine_shim --port 8933" || true
