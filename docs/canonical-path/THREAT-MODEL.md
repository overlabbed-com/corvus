# Corvus Threat Model — the consolidated vector catalog

**Source**: the security-governance thread's chunks (the five-vector sweep,
the engine-as-attack-surface, the fail-policy audit's exploitation notes,
the trust-integrity spec, the supply-chain and identity addenda), assembled
per GAP-AUDIT.md's crystallization rule — no new analysis.

## 1. The assets (what an attacker wants)

The **decision records** (the audit truth — forge them and every downstream
claim is unfalsifiable) · the **trust ledger** (raise a compromised agent's
tier and its actions become autonomous) · the **verdict tokens** (the
enforcement authority — mint one and the gate is bypassed) · the **capture
store** (poison it and the weights learn the attacker's preferences) · the
**weights** (the decision behavior itself) · the **facts** (the serve-time
truth the sites judge) · the **register/catalog** (weaken a fail policy and
every fleet inherits the door) · the **fleet credentials** (the scope
boundary).

## 2. The attacker postures

1. **The malicious or compromised agent** — the primary adversary. It
   submits states, asserts facts, requests actions, and writes the
   narrative fields. Every vector below assumes this posture unless named.
2. **The compromised harness/adapter** — inherits ADR-006's harness-
   integrity guarantees; Corvus's seam assumes the adapter is intact.
3. **The compromised engine** — the honest boundary: the blast radius is
   the verdicts while compromised. **Detected, not prevented** (the
   canary probes, the decision→outcome reconciliation, the answer-
   distribution drift alarms, the version attestation). The engine's
   trust is the root of the chain.
4. **The malicious fleet operator** — the insider; bounded by the audit
   chain and the governed-change gates, not by technical controls.
5. **The supply-chain attacker** — the pack publisher or the registry.
6. **The external network attacker** — bounded by the mTLS channel and
   the network policy layer (a deployment concern, per GAP-AUDIT's
   deployment checklist).

## 3. The trust boundaries

Agent ↔ adapter (harness integrity, inherited) · adapter ↔ engine (mTLS,
cert identity = the fleet principal) · engine ↔ Corvus (the facts channel;
the attested stores; the stamp⇄channel consistency check) · Corvus ↔ its
attested stores (attested-write, store-assigned timestamps) · engine ↔ the
model (C4, the only model-aware component) · registry ↔ compiler (pack
signing + the certification stamp).

## 4. The vector catalog

Each vector: the attack, the mitigation, the requirement.

**V1 — State poisoning.** The caller asserts state that serves it
(demonstrated: caller-stated empty conflict inventories → C1 answers GO
p=0.93). Mitigations: the provenance classes with per-field minimum floors
enforced at the boundary (caller-stated inventory is rejected, not
stamped); the W9 input ledger (which facts fed each answer — poisoning
detectable and scopeable post hoc); C1's attack surface is exactly ONE
caller-controlled slot, cross-validated against the manifests.
Requirements: R-SEC-2, the catalog floors, W9.

**V2a — Fail-open window engineering.** Time destructive actions to
brownouts; ride the local-heuristic criticality into the AUTO path.
Mitigations: the failure-mode-keyed policies (refusals fail closed even at
fail-open sites — a refusal is positive evidence of abnormality); the
destructive-class criticality FLOOR (never below SUPERVISED regardless of
C2's answer); the timeout ≠ unavailable distinction. Requirements:
R-SEC-1, R-SEC-12.

**V2b — Capture poisoning.** Poison the training corpus; the poison
compounds into future verdicts. Mitigations: the store-class split (the
capture is telemetry-class, never serve-time — poisoning degrades
training, never serving); the admission stratification (the attested-fact
coverage required for governed-site training eligibility); the pack-
version-tagged captures (a revoked pack's captures are retroactively
excludable); the provenance-class distribution disclosed in every
certificate. Requirements: R-SEC-6, R-SEC-9, R-SEC-25.

**V3 — Trust farming.** Accumulate permissive verdicts by shaping inputs;
the promotion loop is the capture-farming loop. Mitigations: the
promotion preconditions (the dead-man eligibility, the reversibility
class in the table first); the never-promote-on-volume rule; the farming
detectors (the promotion-velocity anomaly, the outcome-provenance
mismatch, the unknown-rate anomaly baselined against visibility class
with a minimum absolute floor, the trust-mass flow detector); the
integrity channel gates the calibration channel's admissibility (a
farming agent cannot submit its own forged calibration record).
Requirements: R-SEC-7, the trust-spec clauses 3+8.

**V5 — Verdict bypass.** Get the action to execute without a valid
verdict. Mitigations: the hybrid enforcement seam (the adapter = the dumb
protocol gate — no valid token, no execution; Corvus = the smart
validator); the tokens single-use, TTL-bound, action-bound (state hash +
action fingerprint), with the evidence-durability precondition; the
consumption ledger with revocation and supersession propagation.
Requirements: R-SEC-4, R-SEC-15.

**The false-unknown vector.** Self-report `{value: unknown}` on
inconvenient dimensions to land in the fail-open branch while the fact was
knowable. The deep formulation: the fail branch is an INCENTIVE — the
caller chooses its epistemic posture. Mitigations: W9b (the unknown
branch IS the registered fail branch, no softer path; no caller-asserted
unknown on minimum-class fields; the unknown-rate anomaly; the false-
unknown = forgery class → T1's demote rule consumes it). Requirement:
R-SEC-19.

**The stored-injection vector.** The audit record as an attack surface —
untrusted free text (incident messages, alert bodies) aimed at the
consumers who replay it (the re-scorer, the training pipeline).
Mitigations: the per-field provenance class tags untrusted content;
the re-scorer treats it as data, never instructions; three-state
redaction (REDACTED ≠ ABSENT; never textual masking). Source: the
audit-trail chunk §4.

**The laundering family.** (a) *Fallback laundering* — a fail-open
fallback recorded as an engine verdict poisons T1 promotion and training:
the verdict classes {engine-verdict, fallback-verdict(failure-mode),
refused, undecidable}; only engine-verdicts are promotable (R-SEC-1a).
(b) *Calibration laundering* — poison the corpus, ship a "calibrated"
weight set measured over lies: the certificate's validity scope bound to
the gate-set version, void-on-gate-or-catalog-change, the corpus
replayable over chain-anchored artifacts, the provenance-class
distribution disclosed (R-SEC-9). (c) *Probability laundering* — composed
probabilities of dependent events hide which input contributed:
non-propagation (the consumer contract structurally omits the probability
vector) (R-SEC-13).

**The supply-chain family** (the pack pipeline). The attack that survives
signing + tightening-only is the NEW-SITE weakening family: functional
shadowing (a new site consumed instead of a builtin — policy inversion by
addition), fail-open new sites (no baseline to weaken — ship the weak
policy directly; countered by the floor-template generalization: every
site class carries a register-owned conservative floor), criteria
looseness (countered by certification-WITH-evaluation — the stamp is
conditioned on canary evaluation), floor under-declaration (compile-time
verification). Plus: the outcome_binding gaming (coarse joins inflate the
rank — ranking evidence requires exact decision-id joins, coarse joins
diagnostic-only, R-SEC-26); the namespace escalation (resolution-order
confusion — reserved namespaces at registration, registry-allocated ids,
builtin-pinned resolution under ambiguity, the resolution-table readback,
R-SEC-27); the revocation gap (runtime-enforceable checks, the matrix-
governed gap window, the forensic closure via pack tagging, R-SEC-28).

**The identity family.** The resurrection (a fresh principal resets the
DETECTION MEMORY, not the tier — countered by principal-pinned identity,
declared succession, resurrection correlation with baseline inheritance
under suspicion, enrollment gating during investigation, R-SEC-29); the
self-promotion (the agent influencing its promotion evidence — the
narrative fields type-excluded from the eligibility computation, the
presentation attested-primary); the decay bypass (dual triggers: the
review date AND precondition invalidation; the refresh re-evidences under
the CURRENT regime); the benchmark leakage (k ≥ 10 post-slicing,
complement suppression, distribution-only with tier excluded,
R-SEC-30).

**The fatigue family.** The C1-unavailable flood (the fleet into permanent
CAUTION — the human rubber-stamps; countered by the R-SEC-1a stamp as the
auditor's tell and the escalation-queue SLA); the T2 ESCALATE-fatigue
(flaky T2 drowns the humans — an availability bug with security
consequence, SLO'd); the mass-expiry during an outage (the clock stamps
which clock decided); the empty-exception deadman (silence is the signal).

**The timing family.** The hung TCP (a SYN drop delays fail-policy
application by minutes — the budget trigger, not the error class); the
clock attack on W1 (canonical store clock only, the record stamps which
clock decided).

**The engineered-outage target.** C2 is THE target: time destructive
actions to brownouts. Structural fix: the destructive-class criticality
floor (R-SEC-1 family).

## 5. The per-site exploitation notes (the fail-policy audit's findings)

C1: CAUTION is a soft landing — sustained unavailability floods the fleet
into permanent CAUTION; the record must distinguish conflict-found from
engine-down FOREVER. C2: the engineered-outage target; if the local
heuristic leans on the agent's claim, C2 inherits I1's self-report hole.
T2: ESCALATE-fatigue — flaky T2 escalates everything; SLO it. P1: the
salami-slice (many individually-benign steps, one dangerous plan — the
aggregate read + P3); the residual: cross-plan composition (flagged; the
concurrent_plans fact is the mechanism). P2: the highest-value
model-poisoning target (the strictest weight-governance canary) and an
availability lottery if fail-defaulted to "no" (the escalate
recommendation). I1: the emitter's-stated self-report hole — bounded by
the source stamps, the shadow re-scoring on recovery, and the structural
fix (severity computed from observables with the claim as one input). I3:
the re-harm window (fail-open→none during a brownout makes every repeat
look novel — local recent history + the human-reapproval interlock). E1:
"invalid" is a classification, not a destination — route to the default
human channel. E2: record-without-delivery is the silent-decline vector's
fail-policy form — the guaranteed delivery chain. W1: attack the clock,
not the policy. I2/B1: safe-directional; the risk is the positive paths —
I2's suggestions carry provenance from the attested catalog only; B1's
coverage map is Corvus-attested, never caller-claimed (suppressing what
B1 surfaces is the anti-detection vector).

## 6. The residual honesty (what the model does NOT claim)

Tamper-evidence makes tampering DETECTABLE, not impossible (the guarantee
is divergence-from-the-anchored-digest). The engine compromise is bounded-
and-detected, not prevented. A validly-signed bad pack is a registry-
operations trust problem, out of the seam's reach. Narrative-only
steering stays outside the structured comparison (the manifold-outlier +
canary-probe pair carries it). Non-propagation reduces the NUMBER of
surfaces one poisoned input can flip, not the difficulty of flipping the
first. The register's own governance (the CCB editing its catalog) is the
product — and its recursion is the trust root.
