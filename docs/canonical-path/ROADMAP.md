# The Corvus Roadmap — the phased canonical path

Each phase delivers a runnable increment; the phases build in order. No
timeframes — the gates between phases are capability gates, not dates.

## Phase P0 — the prototype (this goal)

The CCB's spine, rebuilt against the canonical path: the event ingest
(the OCSF schema, the data-driven vocabulary), the shared state (the changes
+ events + the target status), and the conflict check (the first-class
contract). Runnable as a single binary; live-checked. The ADR mapping ships
with it.

## Phase P1 — the trust mechanics

The trust ledger rebuilt per ADR-003: the per-(agent, action_type) tiers, the
outcome-driven stats, the tier-change events, the plan approval consuming the
tiers. The hooks' contract (ADR-004) lands with its conformance suite and the
first two real adapters (Claude Code + one of the operator's harnesses).

## Phase P2 — the knowledge and the runbooks

The FMEA runbooks gain their schema and validation gate (ADR-004's pattern:
data, strictly validated); the knowledge base (FTS) rebuilds on the embedded
store; the blind-spot detection (the "what the system doesn't know" backlog)
ports from the old implementation where the concept survives review.

## Phase P3 — the fleet onboarding surface

The self-hosted deployment story: the single binary + the Docker image + the
fleet configuration (the vocabulary, the trust defaults, the SIEM sink); the
onboarding docs; the SDK reduced to the documented HTTP contract (any
language). The Splunk app validated against the rebuilt OCSF events.

## Phase P4 — the estate integration (ADR-006)

The HQG gates emit Corvus events; the Corvus conflict check informs the
gates; the DDR records map to the change records. The homelab deployment
becomes the reference fleet.

## Phase P5 — the product surface

The multi-fleet operational story (the deployment automation, the upgrade
path, the backup/restore); the audit CLI's evidence export; the Splunk app's
release; the commercial story (dabslabs.ai) updated to the rebuilt product.

## The gates between phases

- Every phase: the live checks against the running thing (the capability
  gate, not a date).
- P1→P2: the hooks conformance suite exists and one real adapter passes it.
- P2→P3: the runbook validation gate rejects a malformed runbook (the
  mutation-proven control).
- P3→P4: a fresh fleet can onboard from the docs alone.
- P4→P5: the estate's gates demonstrably emit to and consult Corvus.

## THE acceptance gate (ADR-006, the bootstrap-time promise)

**A new harness reaches full governance parity by shipping only an adapter.**

The test, written down so the product can be judged against it: take a
harness that has never seen Corvus, write one conforming adapter (the hook
contract), and verify that the harness's agents get — without any other
work — the conflict checks, the fleet-wide incident awareness (agent A's
incident visible to agent B's planning), the trust grading, and the audit
trail. The only per-harness artifact permitted is the adapter plus the
minimal local guard. If anything else must be ported, the product has failed
this gate.
