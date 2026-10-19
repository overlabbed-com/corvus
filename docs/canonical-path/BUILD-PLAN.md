# Corvus Build Plan — the ideation's consolidated roadmap

**Source**: the five expert threads' outputs, consolidated into the phased
build sequence. No timeframes — the phases gate on capability, not calendar.

## The phase structure

### P1 — The decision engine + the trust mechanics

**Objective**: the separate lightweight decision-engine service with the
typed site contract, and Corvus's trust ledger + hooks integration — the
wedge's core: C1 (the agent brake pedal) end to end.

**Delivers**:
- The engine service: C0–C7 per ENGINE-DESIGN.md, the contract v1.1 wire
  shape, the site catalog v2 (compiler-derived from the register), the
  capture store with dual precision, the conformance surface (the engine
  ships its own probe; the mutation matrix ships with the corpus)
- The register v2: the 19 sites + the fact layer per DECISION-REGISTER-V2.md,
  the failure-mode-keyed fail policies with the resolution paths, the
  W1–W11 well-formedness enforced by the compiler
- The trust ledger: the strict triple, the outcome contract with the
  row-due obligation, the promotion preconditions, the shadow period, the
  directional fail policies (TRUST-SPEC.md clauses 1–10)
- The hooks contract: the adapter (interception, typed ask/answer, outcome
  emission), the verdict-token protocol (single-use, TTL-bound,
  action-bound, evidence-durability precondition)
- The observe mode: the fleet config, the attempt records, the coverage
  accrual ("observe fills the meter")

**Named build-phase decisions** (from the adversarial review):
the token-issuer's HA/DR strategy and the replay-prevention storage
mechanism; the floor-rejection error payload's structured fields
(failed_fact_id, required_provenance_class, observed_provenance_class);
the validate-only endpoint (the P1 backlog).

**Capability gate**: C1 answers live traffic in observe mode; the capture
store records full-schema decisions; the conformance suite runs green in
CI with the mutation evidence.

### P2 — The escalation system + the operator's console spine

**Objective**: the escalation machinery (the three trigger classes, the
six-component decision packet, the answered terminal state) and the
five-zone operator's screen with the morning sequence.

**Delivers**: the delivery chain (record → queue → deliver-on-recovery →
deadman) · the escalation payload (the seven sections) · the five zones ·
the no-silent-dismissal rule · the in-place actions · the quiet strip's
fail-closed dead-men.

**Capability gate**: an escalation fires end to end (the decision → the
payload → the human answer → the answered state → the calibration channel);
the decline-cases flow the same fabric path.

### P3 — The trust product's ramp + the enforce flip

**Objective**: the observe→enforce ramp operational — the flip gate's
three criteria (the canary re-run, the observe-era reconciliation, the
governed signed change) computed from the observe-era records.

**Delivers**: the calibration certificates (per site × weight version) ·
the readiness meter (the argmin verdict vocabulary) · the promotion queue ·
the four trust surfaces · the enforce-flip gate.

**Capability gate**: a fleet completes the observe→enforce flip on the
evidence-based criteria; AUTO grants are earned only by enforced outcomes.

### P4 — The SaaS seam + the marketplace

**Objective**: the multi-tenant deployment (the auth boundary on, the
config API-managed, the usage chain) and the pack/vocabulary surface.

**Delivers**: the tenancy matrix · the pack supply chain (R-SEC-25–28) ·
the namespace registry · the tier-table generator · the benchmark
(R-SEC-30's aggregation rules).

**Capability gate**: a second fleet runs on the same engine with the
existence-hiding 404s and the per-state-class isolation verified.


## The external dependency statement (the engine's model backend)

**The backend: `clef-flash`** — Cloudflare's joint-schema decision model
served by SGLang (the dev-clef image, digest-pinned), deployed on dp01's
RTX PRO 4500 (GPU-d67e1f24, 32,623 MiB, compute 12.0), BF16, zero
quantization, 19.1 GB weights. It serves the Jev/SystemOne API natively
at `/v1/systemone` — the joint schema head emits one logit per allowed
option per question (no free-form generation, no output parsing), which
IS the v2 design's per-option probability source. The gateway alias pins
`served-model-name clef-flash`.

**The measured provenance** (the bake-off, 2026-10-13, on this corpus and
card): agreement with the homelab's three-model consensus labels on the
232-state held-out split — alert_class 91.8%, severity 80.3%, needs_rca
80.0% — at **p50 73–90 ms per decision**. The boot line on any future
roll is the authority for the KV pool (read max_total_num_tokens off it).

**The availability reality**: one engine on one card, co-tenanted on dp01
(the Lightning on GPU 1 keeps its own engine — untouched). When
clef-flash is down, the designed behavior is the fail-policy floor: the
fleet's autonomy drops to the registered defaults (C1→CAUTION, T2→
ESCALATE, P1→escalate), the escalation queue absorbs the surge with its
SLA and deadman, and the observe/enforce attempt-records make the
degradation visible. **What the operator actually sees**: the escalation
queue depth rises, the at-a-glance line shows the elevated count, and the
quiet strip stays loud. The latency spike (work item 4c) targets this
backend and expects the p50 in the 73–90 ms band.

## The acceptance gate (the ideation's thesis, made testable)

**A new harness reaches full governance parity by shipping only an
adapter.** The test: a fresh agent framework integrates via the adapter
edge alone — no core changes, no register changes — and inherits the
whole organization layer: the decision gating, the shared awareness, the
trust ledger, the audit evidence.

## The build-phase constraints (inherited, not re-derived)

Everything through GitOps (no live patching); everything in a new
worktree; the seed branch merges only when the build plan closes with the
operator's go; the DDRs where the tier or a deny-path requires them; the
estate's adversarial-review machinery gates the consolidated design's
changes.

## The standing artifacts

ENGINE-DESIGN.md (the architecture of record) · TRUST-SPEC.md (the trust
mechanics of record) · DECISION-REGISTER-V2.md (the register design of
record) · ASSUMPTION-LEDGER.md (RESOLVED 20 / IN-FLIGHT 0 / OPEN 0 — fully
closed) · ADVERSARIAL-REVIEW-IDEOATION.md (the review's dispositions) ·
PRODUCT.md (the product definition + the lens).

**The build resumes on the operator's go.**
