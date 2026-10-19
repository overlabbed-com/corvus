# Corvus P1 Work Breakdown — the build's executable shape

**Source**: BUILD-PLAN.md's P1 scope + ENGINE-DESIGN.md's components +
the contract v1.1 + the register v2 + TRUST-SPEC's clauses + the
adversarial review's build-phase decisions + the derivation dossier's
[S]-marked fields. Every P1 capability-gate criterion traces to ≥1 work
package's DoD (§4).

## §1 The work packages (in dependency order)

### WP0 — The register sweep + the seed YAML's v2 update (FIRST — unblocks everything)

**Scope**: resolve the derivation dossier's [S]-marked fields: P1's
declared criteria content · I3's recurrence fingerprint key · P2's
no→escalate disposition · T2's demotion to facts.trust_tier (confirm or
reject) · the new sites' (M1, M2′, M4, M8, M9′, M10, P3) full six-step
derivations · W11 conformance coverage per site. Rewrite
`decision-register.yaml` to the v2 shape (the catalog schema v2's fields:
type, solver, criteria_shape, facts with min_class, resolution,
fail_policy with the resolution paths, on_unknown, status).

**DoD**: the YAML parses against the v2 schema; every site carries the
v2 fields; the [S] items are dispositioned (decided, not deferred); the
compiler's invariants hold (the total map, the declared orderings,
resolution ≤ granularity, the bins-required for scores).
**DDR**: none (the repo's own CI gates it).
**Produces**: the register v2 YAML (the compiler's SSOT).

### WP1 — The contract v1.1 boundary (C0)

**Scope**: the three-stage validator (the envelope → per-site →
criteria-shape); the canonical-form request_hash (JCS-class); the error
envelope with the closed code enum (+ `quota_exhausted`, `missing_fact`,
`provenance_below_floor`, `attestation_mismatch`); the floor-rejection
payload's structured fields (failed_fact_id, required_provenance_class,
observed_provenance_class — the adversarial review's refinement); the
facts-shape validation (the probability payloads barred; the evidence
barred); the consumed-surface answer object (the probabilities
structurally stripped); the sites-as-array duplicate detection.

**Depends on**: WP0 (the schema to validate against).
**DoD**: the conformance fixtures pass (the happy path + every 400 code +
the 422 paths + the answers∪errors invariant + the partial-timeout
behavior); the existence-hiding test asserts; the validator rejects a
below-floor fact with the structured payload.
**DDR**: none.
**Produces**: the contract module + the fixture corpus (the spike's
promotion candidate).

### WP2 — The catalog compiler

**Scope**: the register YAML → the catalog projection (the per-fleet
compile); the compiler invariants enforced (the total resolution map, the
declared orderings, resolution ≤ criteria granularity, the bins-required
for scores, the error-enum coverage of the fixture corpus); the
monotonicity diff-classify stage (the change-class stamp; the
downgrade-acknowledgment gate).

**Depends on**: WP0, WP1.
**DoD**: the compiler rejects an invalid register (each invariant tested
with a negative case); the catalog projection round-trips; the
diff-classify stamps a weakening change and fails the build without the
acknowledgment.
**DDR**: none.
**Produces**: the compiler + the catalog artifact.

### WP3 — The decision core (C3)

**Scope**: the per-site solver dispatch (choice/score × model/rule/lookup
— the human solver arrives with the escalation package, P2); the per-site
timeout slicing; the bounded internal retry; the partial success
(answers + errors map; the answers∪errors invariant; the
fail-closed-timeout tightening); the dependency_failed composition (the
sentinel rule: the fail answers are recognizably-not-answers).

**Depends on**: WP1, WP2.
**DoD**: the fixture-driven dispatch tests pass per solver class; the
timeout slicing isolates a slow site (the batch's other sites answer);
the errors map carries the dependency_failed edge.
**DDR**: none.
**Produces**: the decision core.

### WP4 — The inference adapter (C4)

**Scope**: the clef-flash targeting via `/v1/systemone` (the joint-schema
API — the per-option logits ARE the probabilities); the deadline-aware
retries; the engine-family abstraction (the adapter interface, so a
future engine drops in); the temperature=0 determinism; the attested
usage log (the v1-local form: the tokens in the capture for cost
observability).

**Depends on**: WP1; the dependency statement (the backend named:
clef-flash on dp01).
**DoD**: a live solve against clef-flash returns the typed answers with
the per-option probabilities; the p50 latency sits in the measured band
(73–90 ms); the deadline-aware retry proves on an injected delay.
**DDR**: none.
**Produces**: the adapter + the latency measurement (the spike 4c's
promotion candidate).

### WP5 — The capture store (C5)

**Scope**: the dual-precision rows (answer_full + answer_consumed,
atomic); the non-blocking append (the bounded spool, the overflow
drop-oldest, the capture_dropped metric); capture_status in the
response; the replay index (the SQLite WAL persistence); the
request_hash keying.

**Depends on**: WP1, WP3.
**DoD**: the dual-precision atomicity test (no window where one form
exists without the other); the spool's bounded-size test (the capture
cannot be the disk-filler); the replay returns the answer on the
same-key retry.
**DDR**: none.
**Produces**: the capture store.

### WP6 — The fleet scope resolver (C1-component)

**Scope**: the v1-local posture: the Corvus service identity over
loopback; the fleet-scope language written now so SaaS doesn't retrofit;
the existence-hiding 404s (unknown and unauthorized → 404 identically).

**Depends on**: WP1.
**DoD**: the existence-hiding fixture asserts (known-but-unauthorized →
404 identical to unknown); the scope comes from the authenticated
principal, never the payload.
**DDR**: none.
**Produces**: the scope resolver.

### WP7 — The config loader (C6) + WP8 — The observability (C7)

**WP7 scope**: the git-shipped delivery mode (the catalog projection +
the fleet config land via GitOps); the delivery-indifferent interface.
**WP8 scope**: the per-site/family metrics; the three-state healthz
(advisory only — never trusted by the decision path); the seam metrics
(the budget-exhausted counter, the fail-policy application rate).

**Depends on**: WP2 (WP7), WP3 (WP8).
**DoD**: the loader swaps delivery modes without code change (the
interface test); the healthz three states render; the metrics register.
**DDR**: none.

### WP9 — The fact composer (Corvus-side)

**Scope**: the facts assembly per the sites' required_facts; the
provenance stamps (caller-stated < computed < engine-derived < attested);
the ABSENT/UNKNOWN/STALE statuses (the composer reports unknown, never
fabricates); the world composer's bounded projections (post_state,
planned_activity, plan_aggregate, concurrent_plans, change_window); the
minimum-class enforcement at the boundary.

**Depends on**: WP1 (the facts channel), WP10 (the attested stores).
**DoD**: a fact's stamp⇄source consistency validates; the unknown-status
fact flows to the site's on_unknown branch; the bounded projections stay
bounded (the post_state scoping test).
**DDR**: none.
**Produces**: the fact composer.

### WP10 — The attested stores + the chain grammar (Corvus-side)

**Scope**: the decision records (the four-version provenance block), the
conflict/trust ledgers, the claims, the windows; the store-assigned
canonical timestamps; the chain grammar (attested-write, linked,
append-only, capacity-isolated) over the six record classes; the
chain-walker (the lifecycle-completeness walk, mutation-checked).

**Depends on**: WP1.
**DoD**: the chain-walker walks every decision_id and asserts the
lifecycle or the tombstone; a planted gap fires the walker (the mutation
check); the four-version block stamps every record.
**DDR**: none.
**Produces**: the attested stores + the chain-walker.

### WP11 — The verdict-token issuer + the consumption ledger

**Scope**: the tokens single-use, TTL-bound, action-bound (the state hash
+ the action fingerprint); the evidence-durability precondition (no
persisted-or-queued evidence within the bounded window → no enforcement);
the consumption ledger with revocation + supersession propagation; the
HA/DR decision (the adversarial review's build-phase decision: the
storage mechanism, the replication strategy, the break-glass procedure —
DECIDED in this package's design note before implementation).

**Depends on**: WP10.
**DoD**: a token replays → refused; an expired token → refused; a
token for a different action → refused; the evidence-durability
precondition fails closed on the persist failure; the revocation
propagates to the downstream decision-references.
**DDR**: none.
**Produces**: the issuer + the consumption ledger + the HA design note.

### WP12 — The trust ledger + the promotion rules (Corvus-side)

**Scope**: TRUST-SPEC's clauses 1–10 implementation: the strict triple;
the outcome contract with the row-due obligation (the due-layer rules per
action class; the missing-row detector); the promotion preconditions
(the dead-man eligibility, the reversibility class, the drift coverage);
the shadow period; the directional fail policies (the demotion never
blocks on engine health); the quarantine; the ledger mechanics (the
append-only tier-change events, chain members).

**Depends on**: WP10.
**DoD**: a promotion without the preconditions → refused; a missing
due-row fires the disqualifying event; a demotion executes with the
engine down (the directionality test); the tier changes are chain
members.
**DDR**: none.
**Produces**: the trust ledger.

### WP13 — The Claude Code adapter (the integration — LAST)

**Scope**: the hooks' replacement per the transition plan: the adapter
edge (the interception, the typed ask/answer, the outcome emission, the
verdict-token consume); the observe-mode first (never blocks); the
v1-hook archive's integration surface covered (the CC's 5 hook
registrations → the v2 adapter's edges).

**Depends on**: WP1–WP12 (the end-to-end path).
**DoD**: a live CC session's PreToolUse routes through the adapter to
C1 in observe mode; the decision lands in the capture store; the outcome
emission joins the chain. **This package's install touches the Mac-side
settings — the CC/OMP gate applies to the install step.**
**DDR**: the homelab-k3s DDR for any estate-infra manifest; the Mac-side
install follows the harness's own gates.
**Produces**: the CC adapter.

### WP14 — The conformance surface

**Scope**: the fixture corpus versioned with contract_version; the
mutation matrix shipped + CI-run; the error-enum coverage invariant
(compiler-verified); the two runners (CI + the shipped CLI); the
listener-level mode separation; the run-scoped capture partition.

**Depends on**: WP1 (the fixtures), WP2 (the coverage invariant).
**DoD**: every enum code triggered by ≥1 fixture (the compiler
verifies); each mutant fails the suite; the conformance listener refuses
the production handshake.
**DDR**: none.
**Produces**: the conformance suite (the spike 4a's promotion candidate).

### WP15 — The observe mode + WP16 — The delivery chain

**WP15 scope**: the mode in the fleet config (engine mode-blind); the
attempt records (engine-unavailable → the attested attempt row); the
coverage accrual ("observe fills the meter").
**WP16 scope**: the E2 delivery chain (record → queue → deliver-on-
recovery → deadman); the E1 routing rule (the invalid-vocabulary
escalations to the default human channel).

**Depends on**: WP12 (WP15), WP10 (WP16).
**DoD**: an observe-mode attempt records on the engine outage (the
capture gap visible, not silent); the E2 undelivered-past-SLO fires the
deadman; the E1 invalid lands in the default channel.
**DDR**: none.

## §2 The sequencing

WP0 → WP1 → {WP2, WP6, WP7} → {WP3, WP4} → WP5 → {WP9, WP10} → WP11 →
WP12 → {WP15, WP16} → WP13 → WP14 (cross-cutting, gates the exit).

The parallel tracks: the engine-side (WP3→WP4→WP5) and the Corvus-side
(WP9→WP10→WP11→WP12) proceed concurrently after WP1+WP2; WP13 integrates
last; WP14's mutation evidence gates the phase exit.

## §3 The scattered backlog, consolidated

| Scattered item | Lands in |
|---|---|
| The token-issuer HA/DR + the replay-prevention storage (the adversarial review) | WP11's design note (decided before implementation) |
| The floor-rejection error payload's structured fields (the adversarial review) | WP1 |
| The validate-only endpoint (the adversarial review) | WP1's backlog (the P1 stretch — not gate-critical) |
| The register sweep's [S] fields (the dossier) | WP0 |
| The seed YAML's v2 update | WP0 |
| The spike code's promotion (the contract spike → the fixtures; the latency spike → WP4's measurement) | WP14 / WP4 per the design-change process's promotion rule |

## §4 The capability-gate traceability

BUILD-PLAN.md's P1 gate: *C1 answers live traffic in observe mode; the
capture store records full-schema decisions; the conformance suite runs
green in CI with the mutation evidence.*

| Gate criterion | Work packages |
|---|---|
| C1 answers live traffic in observe mode | WP1 (the contract) + WP2 (the catalog) + WP3 (the core) + WP4 (the adapter) + WP9 (the facts) + WP13 (the CC adapter) + WP15 (the observe mode) |
| The capture store records full-schema decisions | WP5 + WP10 (the chain membership) |
| The conformance suite green in CI with the mutation evidence | WP14 (the corpus + the mutation matrix + the runners) + WP2 (the coverage invariant) |

## §5 The DDR statement (per package)

The **repo-internal packages** (WP0–WP12, WP14–WP16) are gated by the
Corvus repo's own CI (ci-v2.yaml: the lint, the tests, the coverage, the
metrics drift guard, the smoke) — no homelab-k3s DDRs. The
**estate-touching steps** carry the estate's discipline: WP13's install
touches the Mac-side CC settings (the harness's own gates apply); the
k8s deployment (OPS-READINESS's shape, post-P1-build) carries the
homelab-k3s DDRs (NOTIFY tier for the additive deployment; APPROVE for
anything touching existing workloads).
