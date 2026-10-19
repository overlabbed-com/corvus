# Corvus Trust Specification — the trust/escalation mechanics

**Source**: the security-governance expert's trust-integrity skeleton (ten
clauses), the decision scientist's trust-calibration semantics, the fleet
operator's R4 signals + review rulings, the product strategist's four trust
surfaces. The requirement stack R-SEC-1…30 backs every clause.

## The ten clauses

### Clause 1 — Trust key and scope
Tiers keyed on the strict triple (fleet, fleet-qualified agent, action_type);
per-fleet partitioned (R-SEC-6 state class); cross-fleet promotion NEVER
automatic — operator action only; ESCALATE is both the default and the
quarantine state. Identity: principal-pinned (the adapter's credential
attests it; the agent's self-declaration never does); declared succession
(R-SEC-29: a new principal for an existing agent requires an audited
operator declaration; silent unlinking structurally impossible).

### Clause 2 — What moves a tier: the outcome contract (obligation-driven)
Only attested outcomes move tiers. Attestation = signed by the executing
layer, decision-id-correlated, taken at the OPERATOR-CARE LAYER (deploy =
live pod readback; config = the RUNNING pod's config, not the manifest;
publish = the RENDERED page; remediation = alert resolved AND stayed
resolved), checked against the CLAIMED postcondition. **The row-due
obligation**: every consequential action AND decline owes exactly one
attested outcome row at its due layer within its per-class window — a
MISSING due row IS the disqualifying event, detected fail-closed (the
decline row's attested-absence verification is the bypass detector).
Outcome classes: CLEAN SUCCESS = one row; LOUD FAILURE WITH CLEAN RECOVERY
= near-creditable (the WHO field distinguishes autonomous recovery —
creditable — from operator-assisted recovery — a deduction); WRONG-LAYER
ATTESTATION = counts as FAILURE; SILENT FAILURE = DISQUALIFYING. Volume
never substitutes for correctness. Grain: the action CLASS, not the agent.

### Clause 3 — Promotion preconditions (all deterministic, all checkable)
Dead-man coverage for the action class is an ELIGIBILITY precondition (no
dead-man signal = ineligible); the reversibility class must be in the table
before promotion on that class (unknown = impossible); cascade-containment
evidence for classes that have cascaded; drift-detection coverage for the
class's surfaces (drift invalidates ALL past attestation for the class);
diversity + time-span floor + criticality-scaled thresholds; the
never-promote ceiling for destructive/credential/exposure classes.

### Clause 4 — Admissibility
Observe informs, enforce promotes. Promotable evidence = engine-verdict
records with attested outcomes (R-SEC-1a); fallback-verdicts analysis-only;
ad_hoc answers inadmissible (R-SEC-18); observe-mode history buys a faster
SUPERVISED review, never a faster AUTO.

### Clause 5 — The shadow period
The agent PROPOSES; the system EXECUTES under the old tier while outcomes
are attested. The class earns autonomy through attested shadow outcomes,
not the agent's own execution record. Shadow outcomes are decision-id-
correlated and held to the same attestation standards as enforced outcomes.

### Clause 6 — Directional fail policy
Promotion fails closed (hold on unavailable/refused/timeout/malformed).
Demotion NEVER blocks on engine health — demotion executes Corvus-side from
attested incident linkage, independent of the engine (R-SEC-12).

### Clause 7 — The asymmetry
Promotion is slow and multi-evidence; demotion is fast and single-evidence.
Every tier change is an auditable event carrying its promoting/demoting
evidence chain. Integrity-attested outcomes (forgery-class) are a demote
input under the replayability standard: containment first (force-ESCALATE +
alarm + review — reversible), demotion on operator confirmation OR a second
baseline window. An agent with an OPEN forgery-class containment is
INELIGIBLE for promotion.

### Clause 8 — Farming detection
Promotion-velocity anomaly per (agent, action_type); outcome provenance
mismatch; first-flagged-after-promotion cohort analysis; action_type
harm-breadth audit; the unknown-rate anomaly per (agent, fact-class) with
the visibility-class baseline AND a minimum absolute floor; the
trust-mass flow detector (demotion/supervision rate vs recovery rate — a
monotonic decay run without recoveries is either a cascade or an attack).
The promotion review shows the evidence chain, never a count.

### Clause 9 — Quarantine
Credential revocation freezes the trust ledger (no auto-promotion during
investigation) and forces all sites ESCALATE. The refusal stream is the
sensor; quarantine is operator-governed and audited; release requires the
same evidence standard as promotion. Enrollment gating during an open
quarantine (R-SEC-29).

### Clause 10 — Ledger mechanics
Tier changes are append-only events and chain members (R-SEC-10). The tier
READ is a lookup-backed site (the canonical thin site), not model-path —
probabilities on a lookup are fabrication. Tier state is Corvus-side
attested-write. The engine's T1 output is advisory candidacy; the RULES
execute at the ledger.

## The calibration semantics (the scientist's artifact)

**The readiness floor**: per-site × per-action-class × per-direction; the
paired agreement rate (human-vs-engine or rule-vs-outcome, joined by
decision_id over frozen states); the threshold = one-sided lower confidence
bound on permissive-class correctness ≥ the tier's bar, at the confidence
level the tier's blast radius demands; the sample comes from
supervised-trial/shadow evidence, never the current tier's operations;
coverage-starved classes degrade to supervised, never to autonomy.

**The decay function** (event-triggered, not calendar): five events —
weight-version change (freeze + supervise), estate-epoch drift (a
supervision bump, one band), certificate expiry (freeze + recertification
queue), time-floor recertification (a reduced-sample refresh trial;
refused → demote), violations (immediate demotion by rule). **Absent
evidence earns supervision, never demotion.** The five events are
register-quotable cells (four policy artifacts + the violation→demotion
ratchet cell with the registered appeal site running AFTER the demotion).

**The certificate-staleness freeze**: per-site × per-weight-version (a
stale C1 certificate freezes C1-sourced promotions while E2-sourced
continue); the resolution path named (recertification against the current
gate-set lifts it).

**The verdict vocabulary** (emitted as data, never recomputed by surfaces):
READY / NOT-READY(binding-constraint) / SUPERVISED(sparse) / FROZEN(scope+
cause) — an argmin over the certificate's cell table with declared
precedence (FROZEN > NOT-READY > SUPERVISED > READY) and its own W7
horizon. The calibration denominator is the DUE SET (rows due per class
per window; the coverage field discloses delivered-and-attested / due —
a systematically silent agent is now VISIBLE).

## The promise-statement register (the security's addendum)

Every fail-policy cell instantiates the promise grammar: [TRIGGER: failure
code] → [SITE] → [GUARANTEED DEFAULT] → [MODE] → [EVIDENCE STAMP] →
[PROOF: conformance cell + mutation rule + negative control]. The SLA
table is a GENERATED VIEW of the register (never hand-copied);
quotable-cell rules: only proof-backed cells, contested cells marked
under-review, recommendations become promises only upon register adoption.
Enforce-mode promises (uniform + per-code) and the observe-mode overlay
(meta-promise: every cell governs the EVIDENCE written) are in the
register v2.

## The product surfaces (projections of the record store)

Trust Map (agents × domains posture, a PULL surface at decision time) ·
Promotion Queue (the readiness meter as a grid with the named binding
constraint; promotions as governed change records with review dates and
DECAY) · Audit Trail (the tamper-evident legal artifact; entered FROM the
exceptions) · Benchmark (Tier 2, opt-in, k ≥ 10 post-slicing with
complement suppression, distribution-only with tier excluded, attested-only
aggregation — R-SEC-30). The liability shape: procedural, not outcome-based
(the driver's-license model); the evidence chain is the legal defense; the
preconditions are the duty of care; the demotion is the response; the
boundary is process promises only.

**The structural privacy property**: readiness, decay, and freeze compute
entirely from a fleet's OWN records — no cross-fleet data required. Only
the Benchmark crosses fleets.
