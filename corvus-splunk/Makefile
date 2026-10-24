# The corvus-splunk guard — a config-only Splunk app, so `validate` IS the whole guard.
#
# There is deliberately NO venv: validate.py is stdlib-only (json, csv, xml.etree), so
# there is nothing to install and the VENV/PY/PIP/RUFF variables have no meaning here.
# It still runs on the pinned python3.12 for CI parity — bare `python3` on this host is
# 3.15, and a syntax check under the wrong interpreter proves the wrong thing.
#
# Proves: every default/*.conf parses, every dashboard XML is well-formed, every lookup
# CSV has a consistent column count, the transforms/props/nav cross-references resolve,
# and bin/ compiles.
# Cannot prove: that Splunk accepts the app, that the SPL is valid, or that the
# dashboards render — those need a live Splunk instance.

PYTHON ?= python3.12

.PHONY: setup validate cycle clean

setup:  ## Nothing to install — validate.py is stdlib-only, so there is no venv
	@echo "setup: ok — no venv by design: validate.py imports only json/csv/xml.etree"

validate:  ## Parse every conf/XML/CSV, resolve the cross-references, compile bin/
	$(PYTHON) validate.py

cycle: validate  ## The guard, one command

clean:  ## The byte-compile artifacts (validate.py itself writes nothing)
	rm -rf __pycache__ bin/__pycache__ .pytest_cache
	@echo "clean: ok — validate.py writes no artifacts of its own"
