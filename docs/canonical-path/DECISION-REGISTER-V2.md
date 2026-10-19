# Corvus Decision Register v2 — the ideation's consolidated register

**Status**: the ideation's register design, consolidated from all five
expert threads. The YAML (`decision-register.yaml`) updates in the build
phase's first task; this document is the design of record for the v2 shape.

## The v2 delta from the seed (13 sites)

- **W1 splits** per the boundary ruling: `now > expires_at` retires into
  `facts.change_window`; **W1′ (window-lapse disposition)** replaces it —
  choice, enum {expire, extend_until(t), escalate}, fail-closed→expire,
  rule-backed, the extension answer required to carry its bound.
- **C2 restructured**: score → choice over catalog-declared bins {routine,
  notable, critical} with rule-declared thresholds; fail → the
  gate-forcing sentinel bin; the interpolated scalar is display sugar.
- **C1 redesigned**: four-valued verdict {TEXTUAL, LIVE_STATE, SEMANTIC,
  SERIALIZE}; seven-item required_facts (active changes, serve-time object
  ownership, composed-state projection, shared-resource map + calendar,
  ownership registry, open incidents + claimed ownership, incident blast
  reach); re-checks on trigger (base movement, incident start on a shared
  dependency, window entry); the seven→four collapse is the site's judgment
  with deterministic pre-classifications riding in the facts.

**The seven-class conflict taxonomy** (the input spec, from the estate's
real conflicts — the fleet operator's chunk 4):

| Class | What was contested | Estate grounding |
|---|---|---|
| LIVE-STATE | two writers, one object, no git conflict — visible only in serve-time ownership | the Deployment ping-ponging ReplicaSets under Flux (the managedFields two-writer attribution) |
| SEMANTIC | both apply, result broken | the vhost displacement (different files, no textual overlap, one composed route) |
| SERIALIZE | shared resource/ownership; resolution is ORDERING, not exclusion | the bake-off vs production traffic; the CI lane vs deploy lane; the single-Kustomization serialization; the GPU-tenancy races |
| OWNERSHIP | a line owned by an automation | the $imagepolicy marker vs the manual bump (the estate's runbook rule, now data) |
| RESPONSE | two agents, one alert — conflict at response time | M1 |
| SHARED-DEPENDENCY | an incident on a shared dependency blocks every change that rides it | the umbrella-Kustomization freeze ("don't change anything that rides the fire") |
| TEXTUAL | the classic same-file conflict | RARE on this estate (everything runs in worktrees) — the seed C1's inputs were tuned for the LEAST common class |

The seven→four collapse is the site's judgment, with deterministic
pre-classifications riding in the facts as computed-class hints. (The
per-class mapping above — TEXTUAL→TEXTUAL, LIVE-STATE→LIVE_STATE,
SEMANTIC/SHARED-DEPENDENCY→SEMANTIC, SERIALIZE/OWNERSHIP/RESPONSE→
SERIALIZE-context — is this consolidation's inference from the chunk
content, recorded here for the register sweep to confirm; the chunks
named the collapse but not the per-class mapping.)
- **T2 demoted** (proposed, pending the register sweep): a tier lookup is a
  pure read of the attested trust ledger — `facts.trust_tier` with the
  unknown→ESCALATE handling in the consuming sites' `on_unknown` branches.
  T1 (the promotion judgment) remains the site.
- **P2 repaired**: the hazard screen — enumerated, individually decidable
  hazard inputs + a declared rule; the answer carries WHICH hazard fired;
  fail default under review (no → escalate recommendation).
- **E2 repaired**: enum {escalate, record, defer_review}; fail-closed →
  defer_review (the missing enum value IS the abstention); the delivery
  chain (record → queue → deliver-on-recovery → deadman).
- **I3**: the recurrence fingerprint key declared first; then lookup-backed
  over the problem store; fail → unknown-recurrence → problem review.
- **P3 added** (plan-aggregate approval): fires at plan submission AND on
  triggers (a new concurrent plan, a shared-dependency incident);
  consumes facts.plan_aggregate + facts.concurrent_plans.
- **M-sites added** (the fleet operator's ten, classified by the boundary
  criterion): M1 respond-dedup (site; fail→defer-or-page) · M2 splits
  (the measurement fact + M2′ the resolution-declaration site; fail→not-
  resolved) · M4 verification-adequacy (site) · M6 → the evidence lane ·
  M8 contextual-risk-appetite (site; choice over the bounded posture enum) ·
  M9 splits (the reversibility lookup + M9′ the undo-now site) · M10
  lane-validity (site; the attribution enum) · M3/M5/M7 are INPUT FIXES to
  E2/C1/W1 respectively.

## The seed-audit verdicts (the W-criteria audit of all 13 original sites)

Consolidated from the decision scientist's chunk-1 audit (GAP-AUDIT b1).
The three offenders are in the v2 delta above; the remaining verdicts:

- **C1**: shape ✓; CAUTION undefined — the fail policy is safe ONLY if
  CAUTION = hold-for-ack (otherwise a fail-open door in fail-closed
  costume); the conflict-inventory source undeclared. Vague-but-
  salvageable → repaired (CAUTION defined; the inventory attested-minimum).
- **T1**: reclassified rule-backed over attested outcomes (R-SEC-7) — the
  rule forces W5, so T1 gets MORE well-formed. Remaining gaps (landed in
  the trust spec): the declared ladder (+1 step), the asymmetric evidence
  bars (the promote bar ≫ the demote bar), hold-on-unknown-evidence.
- **T2**: a lookup in a decision costume (the model path answers it —
  probe 4); probabilities FORBIDDEN on the answer. → the demotion to
  facts.trust_tier proposed; the canonical THIN SITE.
- **P1**: fail ✓; criteria undeclared — the most expensive vagueness in
  the register (this site IS the trust model's operationalization);
  autonomy-granting → rule-backed; the reason must ride in the answer
  payload (risky-escalation ≠ uncertain-escalation).
- **I1**: defensible WITH a provenance flag ("unassessed — emitter's
  claim"); needs an anchored rubric. Minor. (The self-report hole and the
  shadow re-scoring control are in THREAT-MODEL.md.)
- **I2**: fail ✓; the candidate set must come from state (a choice space
  is only enumerable over supplied candidates); the match confidence
  hidden by id/none. Fix: candidates-in-state + the score in the answer.
- **E1**: well-formed as a deterministic membership test; lookup-backed. ✓
- **B1**: the fail policy defensible (the recency queue discipline); the
  score semantics + the "oldest" clock undeclared. Minor.
- **W1 (seeded)**: a W8 violation — a fused computable predicate (the
  clock) + a judgment (extend?); and a latent W2 violation ({expire,
  extend} has no value for "the window is fine"). → the split (the fact +
  W1′), which fixed both.

**The meta-findings** (register-wide): (1) the seed was an answer-shape
register, not yet a decision register — no state schemas, no decision
rules (W1/W3/W5 unmet across all 13); (2) the fail policies were assigned
by family heuristic — the derived distribution replaced it (2 open / 6
pause / 5 closed; the heuristic scored 2-of-5); (3) noul was a flag
masquerading as a type; (4) no dependency DAG → the composition semantics
were undefined (D3 + R-SEC-13 now own it); (5) the widening surface was
located: shape enforced at the boundary, content and fail policy
caller-authored (the probes' evidence).

## The register v2 site list (19 sites + 1 evidence-lane artifact)

| # | Site | Type | Solver | Fail default |
|---|---|---|---|---|
| 1 | C1 change-conflict | choice (4-valued) | rule | CAUTION (pause) |
| 2 | C2 criticality | choice (3 bins) | model | sentinel bin (critical) |
| 3 | T1 trust-promotion | choice | rule-backed | hold |
| 4 | P1 plan-gating | choice | rule-backed | escalate |
| 5 | P2 plan-safety | choice (hazard screen) | rule | no / escalate (under review) |
| 6 | P3 plan-aggregate | choice | rule | escalate |
| 7 | I1 incident-severity | choice (5-level) | model | emitter's stated, source-stamped |
| 8 | I2 runbook-match | choice | lookup | none |
| 9 | I3 recurrence | choice | lookup (blocked on the fingerprint key) | unknown-recurrence |
| 10 | E1 vocabulary-validation | choice | lookup | invalid → default human channel |
| 11 | E2 escalation-class | choice (3-valued) | model | defer_review |
| 12 | B1 blind-spot-rank | choice | model | oldest |
| 13 | W1′ window-lapse | choice | rule | expire |
| 14 | M1 respond-dedup | choice | model | defer-or-page |
| 15 | M2′ resolution-declaration | choice | rule | not-resolved |
| 16 | M4 verification-adequacy | choice | model | not-verified |
| 17 | M8 contextual-risk-appetite | choice | model | conservative posture |
| 18 | M9′ undo-now | choice | model | abort |
| 19 | M10 lane-validity | choice | rule | red-attribution-default |

**The evidence lane**: M6 reconciliation-effect-prediction — a prediction
is a fact with error bars; never a site answer; the registerable decisions
are the commitments that consume it (C1/P1).

## The fact layer (nine citizens + the provenance schema)

`facts.change_window` {state, expires_at, as_of, source, next_activity/
collision_at} · `facts.planned_activity` (the bounded projection) ·
`facts.post_state` (the bounded projection) · `facts.plan_aggregate` ·
`facts.concurrent_plans` · `facts.plan_approval` (attested, from the
decision record) · `facts.m2_measurement` (the verification measurement) ·
`facts.m9_reversibility` (the reversibility lookup) ·
`facts.trust_tier` (pending T2's demotion).

**The fact schema**: `{name, value | unknown, as_of, source,
provenance_class: caller-stated < computed < engine-derived < attested,
freshness: W7 class, status: present | unknown | stale}` — every fact
carries who vouched for it; ABSENT = composer defect (400 missing_fact);
UNKNOWN = an honest answer (the site's unknown-handling branch fires);
STALE = a value exists but the horizon expired (distinct stamp, same
branch). The minimum acceptable provenance class per field per site is
catalog-owned and enforced at the boundary.

## The type system

Two answer types (choice, score) × four solver classes (model, rule,
lookup, human). The type is what the consumer sees; the solver is what the
auditor trusts. noul demotes to a per-site solver restriction + the interim
quarantine stamp (`solver: model_unregistered`); the split order T2 → E1 →
I3; the thin-site principle: a lookup-backed site is a fact read + a fail
policy + provenance + conformance — in the register because its
unknown-handling is a decision.

## The well-formedness criteria (W1–W11)

W1 decidable inputs · W2 closed output space (including the abstention/
defer value) · W3 typed state schema · W4 failure-mode-keyed fail policy
(+W9b unknown-handling integrity) · W5 well-posed question · W6 declared
uncertainty semantics · W7 validity horizon · W8 atomicity + declared
solver class · W9 state provenance (+W9b) · W10 legibility (the four-field
verdict) · W11 provability (per-failure-mode conformance, provable runs,
mutation-checked negative controls).

## The fail-policy science

The direction taxonomy {open, pause, closed} — the repaired register:
2 open / 6 pause / 5 closed. Five principles: asymmetry (name the
unrecoverable error), source classification (failure modes carry different
evidence), recoverability (every fail answer names its resolution path),
no-softer-path (enumerate every path to a fail disposition), adversarial
design (maximin over the site's own cost matrix including the cost of not
deciding). The six-step derivation procedure for new sites.

## The escalation design

Three trigger classes: failure-escalations (can't answer → the registered
fail branch), band-escalations (won't commit → the expected-cost threshold),
divergence-escalations (contradicts expectations → calibration triage).
The six-component decision packet (frozen at mint). Execution policy ⊥
escalation (confirmation attaches to irreversibility, not direction). The
human as the fourth solver class, enum-bound. Three feedback channels
(execution, calibration, register repair) joined on decision_id +
escalation_id; the **answered** terminal state in the delivery grammar.
