# Corvus Engine Design — the consolidated architecture spec

**Source**: the systems-architect's five-chunk ideation arc + the routing
fold-ins from the security, decision-science, product, and fleet-operator
threads. Every claim traces to a delivered chunk or a live probe.

## 1. The internal architecture — seven components

C0. **Contract boundary** (validator): three-stage (envelope → per-site →
criteria-shape); machine-readable 400 body `{error: {code, site_id?, field?,
message, request_id}}`; provenance-floor check (`provenance_below_floor`);
attestation-mismatch check (stamp⇄channel consistency); facts-shape
validation (probability payloads structurally barred; evidence-class records
barred from the facts channel).

C1. **Fleet scope resolver**: authenticate principal → authorize fleet_id →
resolve config (R-SEC-5: scope from identity, never payload). Unknown fleet →
404 (existence-hiding; known-but-unauthorized → 404 identically).

C2. **Site catalog** (compiler-derived from the register): the guarantee
surface — `{site_id → {type: choice|score, solver: model|rule|lookup,
criteria_shape, facts: {name → {required, min_class, shape}},
resolution: {bands, map, ordering, coarse}, fail_policy_ref, on_unknown,
status}}`. Compiler invariants: total map, declared orderings, resolution ≤
granularity, bins-required for scores, error-enum coverage.

C3. **Decision core** (per-site solver dispatch): type-dispatched
(choice/score); solver-class-dispatched (model/rule/lookup/human); per-site
timeout slicing (not the whole budget); bounded internal retry; partial
success (answers + errors map; the answers∪errors invariant).

C4. **Inference adapter**: the only model-aware component; prompt assembly;
temperature=0 determinism; deadline-aware retries; engine-family abstraction;
attested usage log (SaaS).

C5. **Capture store**: telemetry class; append-only, fleet-partitioned;
dual-precision (`answer_full` + `answer_consumed`, atomic); non-blocking
(B4); `capture_status: recorded | dropped` in the response; the quantization
re-derive check in the chain-walker.

C6. **Config loader**: delivery-indifferent (git-shipped / API-managed /
BYO env+mounted); static engine config vs per-fleet config split.

C7. **Observability + health**: per-site/family metrics; traces; three-state
healthz (healthy / degraded / down — advisory only, never trusted by the
decision path).

**Corvus-side components**: the fact composer (assembles `facts` per the
sites' `required_facts`, stamps provenance classes) · the world composer
(bounded projections: post_state, planned_activity, plan_aggregate,
concurrent_plans) · attested serve-time stores (conflict ledger, trust
ledger, claims, windows, decision records, verdict-token consumption) ·
verdict-token issuer (single-use, TTL-bound, action-bound, evidence-durability
precondition) · the delivery chain (record → queue → deliver-on-recovery →
deadman) · the routing rule (E1's invalid-vocabulary escalations to the
default human channel) · decision-point composition (the registered, versioned
policy artifact).

## 2. Contract v1.1 — the wire delta

Sites-as-array (duplicate detection) · canonical-form request_hash (JCS-class)
· the error envelope with the closed code enum · the consumed-surface answer
object (probabilities structurally stripped; engine-side quantization) ·
version/capabilities endpoint · idempotency_key + replay window ·
register-coupled limits · the facts channel (separate from state) ·
context_refs (claimed) · capture_status · per-type probability specs
(choice: {option: prob} summing to 1; score: the bin distribution as primary)
· determinism per (engine, weights) version · site-id grammar +
namespaces · the provenance-floor rejection · the attestation-mismatch
rejection.

## 3. The store-class partition — five classes + the usage surface

| Class | Examples | Write path | Trust | Read scope |
|---|---|---|---|---|
| Attested serve-time truth | conflict ledger, trust ledger, claims, windows, decision records, verdict-token consumption | Corvus-observed events only; store-assigned canonical timestamps | high | per R-SEC-5 + the shared-target wrinkle |
| Evidence/replay | the facts-appendix (frozen inputs, keyed by request_hash) | Corvus attested persist path, compose-time freeze | high | the re-scorer; the auditor |
| Telemetry | engine capture store | the solve path only, best-effort | low — poison-tolerant | fleet-private |
| Ephemeral | replay cache, quota counters | solve path | low | fleet-private |
| Vocabulary | site catalog, template packs | registry-gated | registry-signed | global read |
| Usage (the billing surface) | attested usage log, hash-chained per tenant | sequence-at-solve, write-async | attested-write | per-tenant + the export surface |

The isolation guarantee per state class: world-state = cross-fleet READ with
fleet attribution (the CCB's point); trust = strictly per-fleet, never
cross-fleet; telemetry = fleet-private (platform-admin exception); vocabulary
= global read, registry-governed write; usage = per-tenant, customer-reconcilable.

## 4. The failure taxonomy — F1–F12

F1 the unreachable engine (the budget trigger, not the error class) · F2 the
slow engine (same failure mode to the client; three-state healthz for the
operator) · F3 the partial answers + the composition rule (required-site
error → the whole decision point escalates) · F4 the schema drift (the
capabilities diff → the conformance run; declare-then-behave) · F5 the
deadline math (client timeout = timeout_ms + measured margin; one retry, same
key) · F7 the retry storm (bounded both ends; `quota_exhausted` 429) · F8 the
facts-channel failure (missing → fail-closed; wrong → visible, not judged) ·
F9 the observe/enforce ramp interaction (the attempt records; the capture gap
visible, not silent) · F10 the replay-cache loss (persisted in the WAL) ·
F11 the cross-tenant noisy neighbor (the fail-policy application rate is the
detection signal) · F12 the registry compromise (signed packs, the compiler's
validation, the register-as-gate).

## 5. The deployment topology — three profiles

**What stays invariant**: the contract v1.1 wire shape · the seven components
· D2 pure-function solve + the three-store inventory · the store-class
partition · the facts channel · the verdict-token protocol · the failure
taxonomy · observe/enforce mode semantics · determinism · capture ·
register-as-gate.

**What changes**: T1 the trust root (loopback → mTLS, cert identity = fleet
principal) · T2 config delivery (git-shipped → API-managed → BYO
env+mounted) · T3 scaling (shard by fleet_id; the replay cache is the hard
part) · T4 the network seam (F5's margin rule absorbs it) · T5 the tenancy
matrix (cross-fleet within a tenant, never cross-tenant) · T6 metering (the
hash-chained usage surface, R-SEC-21) · T7 the Corvus side (per-tenant or
multi-tenant — a product decision).

**The honest ledger** (the separate-service seam): the gains — the
independent failure domain (fail-closed becomes testable and real), thin
multi-tenancy, trust isolation, independent evolution cadences, the
replaceable brain, the clean telemetry/truth boundary. The costs — the
availability dependency (the fleet's autonomy floor drops to the fail-policy
floor during outages), the network hop, the credential fabric, one more
deployable, the drift surface itself, the queueing tail. The net: four gains
cannot be bought any other way; the library alternative fails on the
failure-domain argument alone.

## 6. The conformance surface

The engine ships its own probe: `engine conformance run --base-url`. One
fixture corpus, two runners (CI + the shipped CLI). The fixture catalog:
rule-solver stubs with injectable delay/failure (deterministic; no model
dependency). Two tiers: conformance (deterministic, full behavioral matrix)
/ smoke (staging, live-model liveness). The mutation matrix ships with the
corpus (R-SEC-23: the corpus IS the attack corpus). The error-enum coverage
invariant: compiler-verified at corpus build. Listener-level mode separation
+ the conformance handshake refusal + the run-scoped capture partition
(R-SEC-24). The check list includes the existence-hiding test and the
attestation-mismatch attack. Three-state verdict format. The make cycle
gains the mutation run.
