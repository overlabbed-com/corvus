# The corvus-hooks guard — legacy v1 hooks must lint and import cleanly.
#
# v1 is ARCHIVED (branch v1-archive) and NOT deployed. This is rot protection, not
# a test suite: there are deliberately no tests here. The hooks are stdlib-only
# (json/os/sys/re/subprocess/urllib/platform/typing) so setup installs tooling only.
#
# Most files are scripts with hyphens in the name (corvus-governance.py, ...) and so
# are not importable as modules; corvus_core.py is the one real importable module.

PYTHON ?= python3.12
VENV := .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
RUFF := $(VENV)/bin/ruff

.PHONY: setup lint import fix cycle clean

# Auto-bootstrap: any target that needs the venv triggers setup exactly once, so
# `make cycle` is genuinely the one command on a fresh clone (this is a real file
# target, not .PHONY — it is a no-op while .venv/bin/ruff exists).
$(VENV)/bin/ruff:
	$(MAKE) setup

setup:  ## Bootstrap the pinned 3.12 venv + tooling (the hooks need no third-party deps)
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet ruff==0.17.1 pytest pytest-cov
	@echo "setup: ok — hooks are stdlib-only, no requirements file to install"

lint: $(VENV)/bin/ruff  ## Ruff over every hook, adapter and the shared core (config in pyproject.toml)
	$(RUFF) check .

import: $(VENV)/bin/ruff  ## The real proof: byte-compile every script, then import the shared core
	$(PY) -c "import pathlib, py_compile; \
files = sorted(p for p in pathlib.Path('.').rglob('*.py') if '.venv' not in p.parts); \
[py_compile.compile(str(p), doraise=True) for p in files]; \
print(f'import: byte-compiled {len(files)} scripts')"
	$(PY) -c "import sys; sys.path.insert(0, '.'); import corvus_core as c; \
assert all(hasattr(c, n) for n in ('check_target', 'emit_event', 'classify_intent', 'is_destructive_mcp_tool')); \
print('import: ok — corvus_core imported, public API present')"

fix: $(VENV)/bin/ruff  ## Ruff autofixes (no ruff format — this repo does not use it)
	$(RUFF) check --fix .

cycle: lint import  ## The guard, one command

clean:  ## The venv + the lint/byte-compile artifacts
	rm -rf $(VENV) .ruff_cache __pycache__ adapters/__pycache__
