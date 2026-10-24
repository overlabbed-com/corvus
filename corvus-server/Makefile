# The corvus-server guard — legacy v1 platform (FastAPI) must lint and import cleanly.
#
# v1 is ARCHIVED (branch v1-archive) and NOT deployed; the live product of record is
# corvus-v2. There are deliberately NO tests here — this is rot protection, not a suite.
#
# LAYOUT NOTE: the repo-root CLAUDE.md documents a src/ layout (src/app.py, routers/,
# middleware/, models/...). That doc is STALE — none of it exists on this branch. The
# real corvus-server is two modules:
#     cli/corvus_cli.py       the typer CLI (builds app = typer.Typer(...) at import)
#     modules/soc2/module.py  the SOC 2 APIRouter (builds router = APIRouter() at import)
# There is therefore no package to `pip install -e .` and no app factory to import, so
# this harness has lint + import rather than build + test. See the report for the gap.
#
# python3.12 is PINNED: bare `python3` on this host is 3.15 and would break parity with
# the CI, which runs 3.12.

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

setup:  ## Bootstrap the pinned 3.12 venv + the component deps + the tooling
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --quiet --upgrade pip
	$(PIP) install --quiet -r requirements.txt
	$(PIP) install --quiet ruff==0.17.1 pytest pytest-cov
	@echo "setup: ok"

lint: $(VENV)/bin/ruff  ## Ruff over both modules, using corvus-server/pyproject.toml's own config
	$(RUFF) check cli/ modules/

import: $(VENV)/bin/ruff  ## The real proof: import both modules and assert the objects they build
	$(PY) -c "import sys; sys.path.insert(0, '.'); \
assert sys.version_info[:2] == (3, 12), f'expected 3.12 (CI parity), got {sys.version.split()[0]}'; \
import modules.soc2.module as soc2; import cli.corvus_cli as cli; \
from fastapi import APIRouter; import typer; \
assert isinstance(soc2.router, APIRouter), type(soc2.router); \
assert isinstance(cli.app, typer.Typer), type(cli.app); \
print(f'import: ok on {sys.version.split()[0]} — soc2 APIRouter({len(soc2.router.routes)} routes), typer app {cli.app.info.name!r} ({len(cli.app.registered_commands)} commands)')"

fix: $(VENV)/bin/ruff  ## Ruff autofixes (no ruff format — this repo does not use it)
	$(RUFF) check --fix cli/ modules/

cycle: lint import  ## The guard, one command

clean:  ## The venv + the lint artifacts
	rm -rf $(VENV) .ruff_cache __pycache__ cli/__pycache__ modules/__pycache__ modules/soc2/__pycache__
