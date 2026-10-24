# The Corvus dev harness — the Build > Test > Fix cycle for EVERY component.
# Each component owns its cycle in <component>/Makefile; this file is the umbrella
# that runs them all, so "does the repo work?" has one answer.
#
# Live components (real harnesses): corvus-v2, corvus-sdk, corvus-cli
# Legacy/config guards:             corvus-server, corvus-hooks, corvus-splunk
#   v1 is archived at branch v1-archive and is NOT deployed; its guards exist only
#   so archived code cannot silently rot. No tests are resurrected for it.
#
# The component lists below are NOT cosmetic: the legacy three do not declare
# build/test (nothing to build or test), and corvus-splunk has no lint/fix (it is
# config, not Python). Looping a target over a component that lacks it aborts the
# whole umbrella with "No rule to make target", so each target runs over exactly
# the components that define it.
#
# The interpreter is PINNED to python3.12 (CI uses 3.12). Bare `python3` on this
# host is 3.15, and running the suite on it changes the coverage number enough to
# matter — that mismatch is what the pin removes.

PYTHON ?= python3.12

# Live three: the full harness.
LIVE := corvus-v2 corvus-sdk corvus-cli
# Everything: setup, cycle and clean exist everywhere.
ALL := $(LIVE) corvus-server corvus-hooks corvus-splunk
# Python components: they lint and autofix. corvus-splunk is config (validate only).
PY := $(LIVE) corvus-server corvus-hooks

V2 := corvus-v2

export PYTHON

.PHONY: help setup build lint test fix cycle check clean metrics metrics-check run mutation conformance

help:  ## This list
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/ —/'

setup:  ## Bootstrap every component's venv + deps (fresh-clone safe)
	@for c in $(ALL); do printf '\n== %s ==\n' "$$c"; $(MAKE) -C $$c setup || exit 1; done
	@echo "\nsetup: all components ok"

build:  ## The live three's build proof (the legacy guards have nothing to build)
	@for c in $(LIVE); do printf '\n== %s ==\n' "$$c"; $(MAKE) -C $$c build || exit 1; done
	@echo "\nbuild: all live components ok"

lint:  ## Ruff over every Python component
	@for c in $(PY); do printf '\n== %s ==\n' "$$c"; $(MAKE) -C $$c lint || exit 1; done
	@echo "\nlint: all Python components ok"

test:  ## The live three's tests (the legacy guards have no tests by design)
	@for c in $(LIVE); do printf '\n== %s ==\n' "$$c"; $(MAKE) -C $$c test || exit 1; done
	@echo "\ntest: all live components ok"

fix:  ## The autofix step across every Python component
	@for c in $(PY); do printf '\n== %s ==\n' "$$c"; $(MAKE) -C $$c fix || exit 1; done
	@echo "\nfix: all Python components ok — run `make lint` to confirm"

cycle: setup  ## THE loop: setup, then every component's build > lint > test
	@for c in $(ALL); do printf '\n===== %s =====\n' "$$c"; $(MAKE) -C $$c cycle || exit 1; done
	@echo "\ncycle: ALL COMPONENTS OK"

check: cycle  ## The full gate set (what CI runs) — identical to cycle

clean:  ## Remove every component's regenerable state
	@for c in $(ALL); do $(MAKE) -C $$c clean; done
	@echo "clean: ok — run `make setup` to rebuild"

# ── v2-specific targets, kept at the root for continuity ────────────────────
metrics:  ## Regenerate the committed dev-metrics artifact
	$(MAKE) -C $(V2) metrics

metrics-check:  ## The metrics drift guard
	$(MAKE) -C $(V2) metrics-check

run:  ## The engine up + the live proof
	$(MAKE) -C $(V2) build

mutation:  ## The mutation evidence (the phase-gate target)
	$(MAKE) -C $(V2) mutation

conformance:  ## The conformance run (the phase-gate target)
	$(MAKE) -C $(V2) conformance
