# Corvus Fail-Policy Derivations — the six-step procedure applied per site

**Source**: the decision-scientist thread's chunk 5 (the procedure) applied
at consolidation to the RECORDED per-site data — the direction taxonomy
(chunk 5: 2 open / 6 pause / 5 closed), the fail-policy audit matrix
(security chunk 3), the per-site exploitation notes (THREAT-MODEL.md §5),
and the register repairs (DECISION-REGISTER-V2.md). Reconstructed per the
close-out goal's work item 2.

**Provenance legend**: **[R]** = recorded verbatim in the cited chunk ·
**[D]** = derived at consolidation from recorded data (the derivation
stated) · **[S]** = under-determined by the recorded data, marked for the
register sweep — never invented.

The six steps: (1) name the unrecoverable error · (2) choose the class ·
(3) key by failure mode · (4) name the resolution path · (5) harden
against chosen ignorance · (6) prove it.

## The 13 seed sites

**C1 change-conflict** — (1) [D] the unrecoverable error: proceeding onto
a conflicting change or mid-incident (the false-GO is catastrophic; the
exploitation note's alarm-fatigue vector names the opposite failure) —
derived from the recorded maximin analysis (chunk 5 P5: CAUTION dominates
both GO and STOP). (2) [R] pause. (3) [R] all four modes → CAUTION
(refused additionally writes a refusal record, R-SEC-14). (4) [R] the
escalation queue with an SLA and a deadman; the re-check triggers
re-fire. (5) [R] the record distinguishes conflict-found from engine-down
FOREVER (the auditor's tell); the seven→four collapse with deterministic
pre-classifications. (6) [R] the matrix IS the test plan; the
composition's conservative branch per R-SEC-13.

**C2 criticality** — (1) [R] the false-low criticality riding a
destructive action into the AUTO path (the engineered-outage target).
(2) [R] pause (the sentinel bin forces the approval gate). (3) [R]
unavailable → the local heuristic as FALLBACK-VERDICT(unavailable),
never laundered; refused → conservative unknown=high (a refused caller
never receives a permissive score); timeout → the heuristic + stamp;
malformed → conservative. (4) [R] the approval gate (the sentinel's
resolution path). (5) [R] the destructive-class criticality FLOOR (never
below SUPERVISED regardless of C2's answer). (6) [R] W11 per-mode; the
strictest weight-governance canary (the model-poisoning target).

**T1 trust-promotion** — (1) [R] promoting on absent or unattested
evidence. (2) [R] closed (hold = the identity action — the safe direction
executes autonomously). (3) [R] all four → hold. (4) [R] hold IS the
resolution (no promotion moves); the demotion path is independent
(R-SEC-12: demotion never blocks on engine health). (5) [R] the promote
bar ≫ the demote bar; the never-promote ceiling for
destructive/credential/exposure classes. (6) [R] the directionality
negative control: engine down + attested incident → demotion still fires.

**T2 tier-lookup** — (1) [R] a fabricated tier (a probability on a lookup
is fabrication). (2) [R] pause (ESCALATE, code-stamped). (3) [R] all four
→ ESCALATE. (4) [R] the human decides ABOUT THE SOURCE ("the trust
register is unreachable for agent X: admit, hold, or investigate the
register"), never the tier value — a human is not the tier authority.
(5) [R] lookup-backed, off the model path; probabilities forbidden.
(6) [R] the thin-site conformance (the fail policy + provenance +
conformance machinery). Note: the demotion to facts.trust_tier is
PROPOSED, pending the register sweep [S].

**P1 plan-gating** — (1) [R] auto-executing an untrusted plan step (the
site IS the trust model's operationalization — the most expensive
vagueness). (2) [R] pause (escalate, stamped). (3) [R] all four →
escalate. (4) [R] the human plan review; the reason rides in the answer
payload (risky-escalation ≠ uncertain-escalation). (5) [R] rule-backed
with DECLARED criteria; the aggregate read (per-step tiers AND the plan
aggregate — the salami defense's per-step layer). (6) [R] W11.
[S] the declared criteria content (the register sweep).

**P2 plan-safety** — (1) [R] executing an unsafe plan (the highest-value
model-poisoning target). (2) [R] closed (no — nothing executes), with the
no→escalate recommendation under review [S: the register-owner
disposition]. (3) [R] all four → no (registered); the tier table quotes
it as under-review until dispositioned. (4) [R] the plan author's
revision path. (5) [R] the hazard screen (enumerated, individually
decidable hazard inputs + a declared rule; the answer carries WHICH hazard
fired). (6) [R] W11 + the P2-specific adversarial holdout (the strictest
canary).

**P3 plan-aggregate** — (1) [D] the salami-slice aggregate (many
individually-benign steps composing one dangerous plan) — derived from
the recorded salami defense (the security's P1 note + the architect's P3
birth). (2) [D] pause (escalate) — the escalate default is recorded in
the register v2; the pause classification is the direct reading of the
recorded taxonomy (escalate = pause). (3) [R] escalate (the register v2
default). (4) [R] the plan-level human review; re-fires on triggers (a
new concurrent plan, a shared-dependency incident). (5) [R] consumes
facts.plan_aggregate + facts.concurrent_plans; the three-layer salami
defense (per-step P1 + plan-level P3 + the cross-plan facts). (6) [S]
the new site's conformance is build-phase — marked for the register
sweep.

**I1 incident-severity** — (1) [R] the missed severity (the silent
under-classification; the overstatement direction is the fatigue attack —
the same stamping catches both). (2) [R] open (the emitter's stated,
SOURCE=EMITTER stamped). (3) [R] unavailable → the emitter's stated +
shadow re-scored on recovery; refused/malformed → the UNCLASSIFIED lane
(never low); timeout → stamped. (4) [R] the unclassified lane's human
sweep. (5) [R] the shadow re-scoring (a systematic divergence is a
finding either way); the structural fix: severity computed from
observables with the claim as one input, never the whole answer while
the engine is up. (6) [R] W11 with the provenance flag.

**I2 runbook-match** — (1) [D] a fabricated runbook match — derived from
the recorded positive-path risk (the suggestions must carry provenance
from the attested catalog only). (2) [R] closed (none = no match, safe).
(3) [R] all four → none, provenance-stamped (no runbook ≠ engine couldn't
look). (4) [R] the next tier: the human runbook search. (5) [R] the
candidates-in-state (a choice space is only enumerable over supplied
candidates) + the score in the answer. (6) [R] W11.

**I3 recurrence** — (1) [R] treating a repeat as novel (the re-harm
window: fail-open→none during a brownout makes every repeat of a failed
remediation look novel, killing the chronicity signal). (2) [R] pause
(unknown-recurrence → problem review). (3) [R] any failure code → LOCAL
recent history (upon adoption), stamped. (4) [R] the problem-review
queue; PLUS the interlock promise independent of I3's answer: a
recently-failed remediation requires human re-approval before re-run (a
rule, R-SEC-7 class). (5) [R] the recurrence fingerprint key declared
FIRST (the solver class was undecidable as written); then lookup-backed
over the problem store. (6) [S] blocked on the register edit declaring
the fingerprint key — marked for the sweep.

**E1 vocabulary-validation** — (1) [R] a fabricated vocabulary match.
(2) [R] closed (invalid). (3) [R] all four → invalid → routed to the
DEFAULT HUMAN CHANNEL + alarm ("invalid is a classification, not a
destination"). (4) [R] the routing rule's delivery chain. (5) [R]
lookup-backed membership test against the catalog-owned vocabulary.
(6) [R] the nonexistent-vocabulary negative control (the test must be
able to fail).

**E2 escalation-class** — (1) [R] the MISSED escalation (silence — the
fail-open fired exactly under correlated failure and defeated the site's
purpose; incident 1 maps here verbatim). (2) [R] pause (defer_review).
(3) [R] unavailable → record → queue → deliver-on-recovery → deadman
past SLO; refused → the refusal record + human surface; timeout →
record + stamp; malformed → the default channel + alarm. (4) [R] the
guaranteed delivery chain (record-without-delivery is not a terminal
state). (5) [R] the third enum value {escalate, record, defer_review} IS
the abstention; the observe-mode delivery chain runs too (the rehearsal).
(6) [R] the undelivered-past-SLO deadman test.

**B1 blind-spot-rank** — (1) [D] a fabricated coverage map (the
anti-detection vector: suppressing what B1 surfaces) — derived from the
recorded positive-path risk. (2) [R] open (the oldest, stamped — the
recency queue discipline). (3) [R] all four → oldest + stamp. (4) [R]
the next cycle (self-correcting — the degenerate resolution path, chunk 5
P3). (5) [R] the coverage map is Corvus-attested, never caller-claimed.
(6) [R] W11.

**W1′ window-lapse** — (1) [R] the unauthorized widening (an unbounded
"extend" is the hazard the enum refuses to express). (2) [R] closed
(expire — an unanswerable disposition never defaults to the widening
direction). (3) [R] all four → expire (canonical clock only, the record
stamps which clock decided — the clock attack vector). (4) [R] the
window-renewal path (the operator's calendar). (5) [R] the extension
answer carries its BOUND (extend_until(t), bounded by a declared max and
capped by the next planned activity); escalate is the gray band. (6) [R]
W11; rule-backed (declared rule over work-in-flight ∧ collision calendar
∧ bounded max — no model path).

## The new sites (the recorded defaults; the derivations marked for the sweep)

The register v2 records the fail defaults for M1 (defer-or-page), M2′
(not-resolved), M4 (not-verified), M8 (the conservative posture), M9′
(abort), M10 (red-attribution-default), P3 (escalate). The six-step
derivations for these sites were not delivered in the chunks — the
defaults are [R], the full derivations [S: for the register sweep], with
one recorded anchor each: M1's fail branch must never silently ignore
(the escalation machinery absorbs the surge); M2′'s fail closes incident
closure (never close on unknown); M9′'s fail aborts (the mid-flight
sibling of C1); M8's fail selects the most conservative posture; M10's
fail defaults to fleet-wide attribution (the conservative reading of a
red).

## The aggregate check

The dossier's class column reproduces the recorded distribution exactly.
The 13 seed sites: 2 open (I1, B1) · 6 pause (C1, C2, T2, P1, I3, E2) ·
5 closed (T1, P2, I2, E1, W1′) — the recorded 2/6/5. P3 is a NEW site
(born after chunk 5's classification) with a recorded pause default; it
is not part of the 13-site distribution. No site's class was re-derived
differently from the record.
