# Architecture Decision Records — the canonical path

Each ADR: the decision, the context (from the source review), and the
consequences. Statuses: ACCEPTED (the canonical path's decisions) /
PROPOSED (needing the operator's confirmation).

## ADR-001 — Self-hosted single-binary per fleet; multi-agent, not multi-tenant SaaS

**Decision**: Corvus deploys as one self-contained binary (the API + the
embedded SQLite) per fleet. The concurrency model is many agents per fleet;
the tenancy model is one deployment per fleet. No SaaS multi-tenancy in the
core.

**Context**: the review (SOURCE-REVIEW.md) found the old code single-tenant
(the deployment identity implicit); the product-first claim targets other
fleets. The README's framing (self-hosted, the SIEM forwarding, the per-fleet
secrets) is self-hosted-per-fleet, not SaaS.

**Consequences**: the fleet identity is the deployment's configuration, not a
row column — the data model stays flat; the multi-fleet scale is operational
(more deployments), not architectural; the embedded database keeps the
deployment story at docker-run; the isolation story is the deployment
boundary, which is what a CCB wants anyway (a fleet's change control is its
own).

## ADR-002 — The event vocabulary is data, the schema is code

**Decision**: the event-type registry moves to configuration (the fleet's
vocabulary, validated server-side against the OCSF class map); the core
lifecycle types (the change/incident/remediation/sweep/session families) ship
built-in; the custom types register without a code change.

**Context**: the review found the hardcoded `EVENT_TYPE_ALLOWLIST` frozenset
(models/events.py:11-50) — every new type is a release, a tax the product
cannot carry for other fleets.

**Consequences**: the strict schema stays (the OCSF classes, the validation)
— the flexibility is the vocabulary, never the shape; a misconfigured
vocabulary fails loudly at registration, not silently at ingest.

## ADR-003 — Trust is per (fleet, agent, action_type); outcomes move the tiers

**Decision**: the trust ledger's key becomes (agent, action_type) within the
fleet deployment. The tiers: AUTO / SUPERVISED / ESCALATE (unchanged
vocabulary). The mechanics the old code lacked: the outcome events
(action.approved/denied, incident.linked-change) adjust the tier's stats; the
tier changes are themselves emitted events (`trust.promoted`,
`trust.demoted` — added to the built-in vocabulary); the plan approval reads
the tiers per step.

**Context**: the review found the tiers global-per-action_type with no
promotion mechanics (the README's "promote/demote based on outcomes" was
aspirational).

**Consequences**: an agent earns autonomy by its own record; the tier
changes are auditable events (the CCB's own decisions are on the record);
the ESCALATE default stays safe.

## ADR-004 — One hook enforcement contract; per-harness adapters are thin shims

**Decision**: the product ships ONE hook contract — the stdin JSON in (the
tool name, the input), the conflict-check call out, the exit-code decision
(0 allow / 2 block) plus the post-action event emission — and a conformance
suite for it. Every harness adapter (Claude Code, DSH, OMP, Pi, Codex, …) is
a thin shim over the contract, proven by the suite.

**This is the product's most load-bearing interface** (ADR-006): the adapter
contract IS the bootstrap. A new harness inherits the full governance stack
— the conflict checks, the fleet awareness, the trust grading, the audit
trail — by shipping one conforming adapter. The contract's stability and its
conformance suite are the bootstrap-time promise, made testable.

**Context**: the review found the README claiming ten tools with three thin
adapters; the harness landscape now includes the DSH/OMP/Pi systems with
their own hook/extension mechanics; the HQG stack independently converged on
the same enforcement point.

**Consequences**: a new harness costs an adapter, not a governance
implementation; the conformance suite is the product's compatibility gate;
fail-open on unreachability stays for the delegated intelligence while the
minimal local guard (ADR-006) stays fail-closed — the availability trade is
layered, not binary.

## ADR-005 — The dependency graph is relational; Neo4j is an export

**Decision**: the dependency graph and the blast-radius queries live in the
embedded database (the edges table + the recursive queries). The Neo4j
forwarder becomes an optional export (like the SIEM forwarder), not a core
dependency.

**Context**: the review found Neo4j as a hard dependency (graph.py, 437
lines) for queries that fit the relational model; the deployment tax (a
second database) contradicts ADR-001's single-binary story.

**Consequences**: the blast-radius capability keeps its depth (the recursive
traversal); the deployment gains simplicity; a fleet wanting Neo4j gets the
export path.

## ADR-006 — ACCEPTED: governance lives in Corvus; harnesses plug in

**Decision (ACCEPTED per the operator's direction, 2026-10-18)**: Corvus is
the harness-independent governance layer. The classification, the conflict
check, the trust tiers, the event fabric, and the change records live in the
Corvus service. A harness reaches full governance parity by shipping ONE
thin adapter over the hook contract (ADR-004) — the per-harness governance
bootstrap collapses to adapter-writing.

**The rationale is the bootstrap time** (the operator's framing): every new
harness that drops — and one will — currently demands porting the governance
stack, re-deriving the enforcement, and tweaking it over time. That per-tree
cost is the friction Corvus exists to remove. The operator's acceptance
criterion, verbatim in intent: *agent A finds an incident in a component and
the rest of the fleet knows outside of any session — "I'm working on this
thing, so if it's in your planning or your critical path, you need to know."*
Cross-functional awareness lives outside every session because it lives in
the service.

**The layered exception — the minimal local guard**: the harness keeps a
tiny, stable, fail-closed local guard (the hard-fail destructive patterns,
the DDR presence check) that never depends on a network hop. Everything else
— the fleet picture, the conflict checks, the trust, the events — delegates
to Corvus. The guard is what survives a Corvus outage; the intelligence is
what a new harness inherits by plugging in.

**Consequences**: the HQG stack's long-term shape becomes the adapters plus
the local guard — its SSOT files (the classifier, the schema) migrate toward
Corvus's service surface over time; the hook contract (ADR-004) becomes the
product's most load-bearing interface, because it IS the bootstrap; the
Corvus server's availability becomes a governance dependency, which is why
the local guard exists and why the server's own health is a first-class
concern.

## ADR-007 — The state model keeps the spine, drops the mesh, fixes the matching

**Decision**: the ten-table spine survives (changes/events/incidents/problems/
cmdb/ci/audit/triage/steps/knowledge). The mesh-federation columns
(node_id/hlc_timestamp/mesh_sync_status/synced_peers) are dropped — except the
event ordering quality, preserved via the HLC as the event's timestamp source
(single-node causal ordering across agents). The target matching becomes
exact-and-relational: the targets normalize into a change_targets table
(change_id, target) with exact matching, replacing the LIKE-on-JSON.

**Context**: the review found the mesh columns on every table serving an
empty `src/mesh/`, and the LIKE matching false-positive/negative-prone.

**Consequences**: the schema loses its dead weight; the conflict check gains
correctness; the HLC salvage keeps the event-ordering quality the federation
ambition was reaching for.
