# Corvus Security Requirement Catalog — R-SEC-1 through R-SEC-30

**Source**: the security-governance thread's chunks and addenda, assembled
per GAP-AUDIT.md's crystallization rule. Each requirement: the derivation
(the vector or consumer that demanded it), the mechanism, and the
amendments where later chunks modified it. The full vector context lives
in THREAT-MODEL.md; the trust mechanics in TRUST-SPEC.md.

**R-SEC-1 — Failure-mode-keyed fail policies.** From V2a: "hammer the
engine until it refuses me" becomes a pass-button on fail-open sites
otherwise. Keyed by {unreachable, caller_refusal, dependency_failed,
timeout, out_of_enum}; the timeout ≠ unavailable (a timing anomaly on a
safety-critical check halts, never silently proceeds); every fail answer
provenance-stamped and recognizably-not-an-answer.
*R-SEC-1a (amendment)*: fallback verdicts are a distinct evidence class in
BOTH modes — {engine-verdict, fallback-verdict(failure-mode), refused,
undecidable}; only engine-verdict records are promotable evidence.

**R-SEC-2 — The engine-owned fact channel.** Facts are a separate
top-level field; `required_facts` per site; the engine validates shape,
never truth. (a) facts separate from state: adopted; (c) the engine
validates shape: adopted; (b) engine-judges-facts: rejected.
*Amendment*: the narrative-vs-fact divergence detector has a REGISTERED
OUTCOME (divergence → CAUTION/refusal/alarm is a policy choice in the
register, not a logging sensor) — it lives in the composition policy's
`on_divergence`.

**R-SEC-3 — The canonical identity service.** The strict trust triple
(fleet, fleet-qualified agent, action_type) keys all trust state; the
agent identity is principal-pinned (the adapter's credential attests it),
never the agent's self-declaration.

**R-SEC-4 — The enforcement seam (hybrid).** From V5. The adapter = the
dumb protocol gate (no valid token, no execution); Corvus = the smart
validator (the issue, the consume, the ledger). Tokens: single-use,
TTL-bound, action-bound (state hash + action fingerprint — a GO for
deploy does not cover delete), with the evidence-durability precondition
(no persisted-or-queued evidence within the bounded window → no
enforcement). The consumption ledger carries revocation; supersession
propagates to downstream decisions.

**R-SEC-5 — Fleet scope from authenticated identity.** The payload
fleet_id is a routing key; the authenticated principal determines scope.
Unknown fleet → 404, known-but-unauthorized → 404 IDENTICALLY
(existence-hiding). Network policy is a second layer, never the
isolation.

**R-SEC-6 — The store-class split.** From V2b. Five classes + the usage
surface (attested serve-time truth, evidence/replay, telemetry, ephemeral,
vocabulary, usage-chain) — each with its write path, trust class,
retention tier, and read scope. The capture is telemetry-class:
poisoning degrades training, never serving. The isolation guarantee is
per state CLASS (world-state: cross-fleet READ with attribution; trust:
strictly per-fleet; telemetry: fleet-private; vocabulary: global
registry-governed; usage: per-tenant, customer-reconcilable).

**R-SEC-7 — Rules decide, models advise.** The decision's EFFECT
(autonomy-granting) requires the rule-backed form over attested outcomes;
learned signals may rank or annotate, never sit in the rule's condition.
Attested outcome = {observer_signature (harness/actuator-signed, never
self-reported), decision_id, outcome_class, occurred_at}.
*Amendments*: (1) integrity-attested outcomes (forgery-class events) are
a demote-rule input under the REPLAYABILITY standard, with the
containment-then-demote ladder and the promotion-eligibility freeze; (2)
the narrative fields are type-excluded from promotion eligibility/ranking
(presentation attested-primary); (3) the demotion never blocks on engine
health (see R-SEC-12).

**R-SEC-8 — The fleet quarantine kill-switch.** Credential revocation
freezes the trust ledger (no auto-promotion) and forces all sites
ESCALATE; the refusal stream is the sensor; release requires the
promotion evidence standard. Enrollment gating during an open
investigation (with R-SEC-29).

**R-SEC-9 — Weights-artifact governance.** From V2b/V3. The holdout
gates, the shadow window, the rollback, the version attestation.
*Amendments*: (1) the capture-resistance metric is a REQUIRED,
register-thresholded, tier-tightened gate predicate (the scientist owns
the metric; the register owns the threshold; computed on chain-anchored
frozen states, scoped to fact-dimensions with the narrative blind spot
named); (2) the promotion gate consumes the regression bounds AND the
calibration certificate as a CONJUNCTION, fail-closed, keys {site,
engine, weights, gate-set, window, catalog}, void-on-gate-or-catalog-
change, corpus replayable + provenance-class distribution disclosed; (3)
the coverage floor (delivered-and-attested / rows DUE — the systematically
silent agent becomes visible).

**R-SEC-10 — Ledger tamper-evidence stack.** Per-record signatures (the
full audit payload), per-fleet hash chains COVERING TOMBSTONES (a chain
over only "valid" records lets deletion hide as invalidation), the
external anchor (a separate recompute-before-publish anchorer with its
own credential, max(interval, volume) cadence, the missed-anchor deadman),
WORM retention with the GOVERNED TOMBSTONE path (annotation-as-append;
immutable-by-construction, correctable-by-annotation). The chain grammar:
attested-write, linked, append-only, capacity-isolated — over six record
classes, no second-class records; the chain-walker (mutation-checked)
with the quantization re-derive check.

**R-SEC-11 — Mode-aware evidence.** Every record carries the
observe/enforce flag; OBSERVE INFORMS, ENFORCE PROMOTES; the enforce flip
is a governed weights-class change gated on the canary re-run + the
observe-era reconciliation + the signed change. Observe mode is the
flooding stage: the capture-admission controls live from day one.

**R-SEC-12 — Directional fail policies.** Promotion fails closed (hold on
every failure mode); DEMOTION NEVER BLOCKS ON ENGINE HEALTH — demotion
executes Corvus-side from attested incident linkage (a fail-closed T1
that froze demotion would pin a compromised agent at its stolen tier).

**R-SEC-13 — The composition policy.** How mixed answers∪errors compose
into a verdict is a registered, versioned artifact stamped into the
decision record; fail-conservative (any error at a gating site forces the
conservative branch). The compiler derives it; the conservativeness
ordering is declared (an undeclared ordering is a compiler-rejected bug).
*Amendment (non-propagation)*: probabilities do not propagate across the
DAG — enforced in the consumer contract's TYPES (the answer object
structurally omits the probability vector); composition consumes typed
answers + provenance; the poison's reach is bounded at the site it
entered.

**R-SEC-14 — Fail-toward-a-human.** Every conservative default includes a
guaranteed human surface (the default channel, the delivery chain, the
deadman); refusal records are chain members with a human-surface SLO.
"Fail-closed" is defined as fail-toward-a-human, not fail-toward-a-record.

**R-SEC-15 — The evidence/telemetry split.** The authoritative record is
Corvus-side attested-write; the capture is best-effort with
capture_status; the paths are capacity-isolated; enforce-mode actions
require persisted-or-queued records; record-persist failure = fail-closed
+ deadman. Mirrored on the precision axis: full precision is born, measured,
and audited inside the engine; only declared, ordered, mapped bands cross
the boundary (every crossing re-derivable from the record).

**R-SEC-16 — The facts-freeze.** Re-decidability requires snapshotting
fact VALUES at decision time (the facts-appendix, keyed by request_hash,
the fifth store class, compose-time freeze, record-lifetime retention,
hash-verified). The freeze includes the complete W9-classified state AND
the unknown states (how a weight set behaves on unknowns is part of its
behavior); the 1:1 invariant (one request_hash ↔ one appendix entry ↔ one
decision record ↔ one capture row) is store-enforced.

**R-SEC-17 — The four-version provenance block.** Register + catalog +
weights + engine build, mandatory in every record — the auditor's "why
GO" chain (state × policy × site-defs × judgment × integrity). The
catalog version stamp is what makes "audit first, freeze second" safe
across the repair boundary.

**R-SEC-18 — Ad-hoc inadmissibility.** Ad-hoc answers are recorded but
inadmissible as promotion evidence; governed-site records carry the
instruction provenance (canonical catalog instructions vs
caller-influenced — the steering-widening variant becomes auditable).

**R-SEC-19 — Unknown-handling discipline.** From the false-unknown vector.
The unknown branch IS the registered fail branch (one disposition per
epistemic class); no caller-asserted unknown on minimum-class fields
(boundary-rejected; attested-value-but-reported-unknown = forgery class);
the unknown-rate anomaly per (agent, fact-class) baselined against
visibility class WITH a minimum absolute floor (a detector feeding trust
punishments is held to a precision standard); unknown vs stale stamped
distinctly (the lattice: fresh → stale-within-tolerance → stale-beyond →
unknown, catalog-owned tolerances); the falsity detection is replayable
over chain-anchored artifacts.

**R-SEC-20 — The precision/resolution security review.** Per governed
site: the threshold-binding form (bands vs continuous cutoffs —
continuous cutoffs flagged; the flippable boundaries become a finite,
declared, auditable set); the gradient-leakage exposure (fine displayed
precision is a probing side channel); catalog-owned + version-stamped (a
resolution re-map is a register-class change that voids affected
certificates); the consumption/evidence precision split (quantize at
consumption, keep precision at evidence — engine-side, pre-boundary).

**R-SEC-21 — The usage chain.** From the billing-integrity vector. The
usage log is its own hash-chained store surface (the chain's threat is
OMISSION, vs the appendix's MUTATION); per-tenant never-reset chains with
genesis-generation markers; signed rollups as the billing artifacts; the
billing witness (usage ⇄ capture joined by request_hash, the solver-class
denominators as the expected-usage model); the customer-reconcilable
export ("audit our metering", not "trust our metering").

**R-SEC-22 — Sequence-at-solve.** The usage sequence is assigned on the
decision path at solve time; the WRITE is asynchronous (a metering outage
degrades billing, never decisions); ONE dispatch path for fair-share
queueing, usage sequencing, and decision ordering — reordering games
would require corrupting the engine's core, which everything else
witnesses.

**R-SEC-23 — The corpus IS the attack corpus.** The conformance fixtures
include the attack fixtures (the 400/422 paths ARE attacks); the mutation
matrix ships with the corpus and CI runs it (a suite that cannot fail
proves nothing); the error-enum coverage invariant is compiler-verified at
corpus build (an uncovered code = build failure).

**R-SEC-24 — The conformance blast radius.** Listener-level mode
separation (the production listener refuses the conformance handshake);
the run-scoped capture partition (structural separation, never
marker-and-filter — conformance captures were never admitted because they
were never in the partition); the namespaced fixture version marker.

**R-SEC-25 — Pack poisoning defense.** The new-site weakening family: the
floor-template generalization (every site class carries a register-owned
conservative floor per failure-mode cell — a new site must meet or exceed
it); the compile-time overlap/shadowing check against DECLARED decision
domains; certification-WITH-evaluation (the stamp is conditioned on the
canary set, the stamp is the observe phase's output); the compile-time
floor verification; the pack-version-tagged captures (retroactive
training exclusion).

**R-SEC-26 — Outcome_binding join governance.** Ranking evidence requires
EXACT decision-id joins (the multiplicity bound: distinct decision_ids,
never matched rows); only attested, correct-layer, engine-verdict-
correlated outcomes are ranking-eligible; coarse joins are
DIAGNOSTIC-ONLY; an unjoinable outcome is INADMISSIBLE, not coarse-joined
(the coarse fallback IS the exploit path); govern the JOIN DECLARATION,
not the outcome stream.

**R-SEC-27 — Namespace registry integrity.** Reserved namespaces enforced
at REGISTRATION; registry-allocated pack ids (the provenance chain:
publisher → allocation → signature → certification); resolution PINNED TO
BUILTIN under any ambiguity (ambiguity resolves toward the higher-trust
class); typosquat screening; the resolution-table readback (for every
builtin site, the resolved definition == the builtin definition — an
impersonation test that can fail).

**R-SEC-28 — Revocation integrity.** Revocation is RUNTIME-ENFORCEABLE
(the catalog load verifies against the registry CRL-style with periodic
re-check; check failure = fail-closed per the failure-mode matrix); the
gap window is governed by the matrix (revoked sites' fail policies fire);
the revocation/recompile events are chain members; the gap duration is an
SLA metric and quotable promise material; the forensic closure via pack
tagging ("you cannot always prevent the gap; you can always account for
it"); the recompile diff includes the composition-policy impact.

**R-SEC-29 — Identity continuity.** The agent identity is the PRINCIPAL
the adapter's credential attests; rotation changes the credential, never
the principal. Declared succession (no silent unlinking — a new principal
for an existing agent requires the operator's audited declaration and
inherits the investigation flags); resurrection correlation (new-principal
enrollment correlated against recently demotion/quarantine-linked
principals; behavioral fingerprint match → auto-flagged to SUPERVISED
review with baselines SEEDED FROM the suspected predecessor); enrollment
gating during an open quarantine.

**R-SEC-30 — Benchmark aggregation.** k ≥ 10 POST-SLICING (the floor
applies after every slicing dimension); complement suppression (publish a
cell only if its complement also meets k — the differencing guard);
suppression, NOT noise (suppressed cells are auditable; noised cells
invite reconstruction); the distribution-only schema ({domain,
cohort-cell, n-as-range-or-suppressed, percentile bands, window} — no
per-agent rows, no raw score lists, NO TIER as a published dimension);
the governed, revocable opt-in; attested-only aggregation (wrong-layer
attestations in the benchmark would rank nonsense in public).

## The cross-cutting mechanisms (the architect's schema details, per GAP-AUDIT a-c1)

**The source-credential stamp** (every fact): `{component:
<corvus-component-id>, credential: <cert-identity>, attested_at:
<store-assigned ts>}` — component-level attribution for facts (humans
attest at the CHAIN level, via Corvus's auth surfaces; two planes). The
boundary validates stamp⇄channel consistency: a stamp claiming a
credential the channel didn't present → 400 `attestation_mismatch`
(the forgery class detectable at the boundary, not in next week's audit).

**The decision_ref schema** (the engine-derived provenance class):
`{decision_id, site_id, answer_digest, validity: live | superseded |
revoked, as_of}` — the answer_digest is the referenced answer's
canonical-form hash (the D1→D2 chain tamper-evident end to end);
supersession extends to decision-references; the decision DAG is acyclic
by construction (a cycle is a compose-time failure).

**The dual-copy witness**: the capture row's facts and the appendix's
facts are two independent copies of the same inputs — in canonical form
they must be BYTE-IDENTICAL; divergence = forgery or corruption evidence,
alarmable. The join grammar: `decision_id → decision record →
request_hash → {appendix entry, capture row}` — request_hash is the sole
cross-store key.

## The amendment ledger (which chunks modified which requirements)

R-SEC-1a (chunk 2.5) · R-SEC-2's divergence-outcome (chunk 5 addendum) ·
R-SEC-7's three amendments (the capstone + the trust-surfaces addendum) ·
R-SEC-9's three amendments (the uncertainty routing + the audit-trail
routing) · R-SEC-13's non-propagation (the uncertainty routing) ·
R-SEC-6's fifth class + the usage surface (the SaaS-shape fold-in).
Every amendment was adopted by the security thread itself in a later
addendum — no requirement was weakened by amendment; the tightening-only
ratchet held across the thread.
