# Corvus Escalation Spec — the payload, the triggers, the grammar

**Source**: the fleet-operator thread's chunk 2 (the seven-section payload)
+ the decision-scientist thread's chunk 4 (the trigger taxonomy, the
decision packet, the human as the fourth solver class), assembled per
GAP-AUDIT.md's crystallization rule.

## 1. The trigger taxonomy (three classes, not one knob)

**Failure-escalations** — the engine cannot answer (unreachable, refusal,
dependency_failed, timeout). No threshold involved; the branch is
registered in the failure-mode-keyed map. Routes to the operational queue.

**Band-escalations** — the engine ANSWERED but no option clears the
declared bar (the gray band). The threshold is an EXPECTED-COST
comparison, not a confidence number: the band's edges sit where the
expected cost of the best autonomous action crosses the expected cost of
human intervention. Properties: the band is asymmetric per direction
(wider on the expensive-error side — C1 needs far more confidence to
auto-GO than to auto-STOP); per-site, catalog-declared; the middle option
absorbs part of the band (which is why CAUTION must be DEFINED as
hold-for-ack). **Answer-execution and escalation are orthogonal axes**:
the confirmation trigger is irreversibility and blast radius, not the
answer's direction — STOP auto-executes with notify (the safe direction);
GO must clear the band AND the execution policy; the trust ladder is the
per-agent overlay on the band/execution lattice. Routes to the
operational queue as a decision packet.

**Divergence-escalations** — the engine answered CONSISTENTLY but the
answer contradicts the register's own expectations (the baseline bounds,
the paired disagreement, a rule-backed answer contradicting a model-backed
one). Epistemically the strongest trigger: divergence is evidence of a
BROKEN ASSUMPTION, not missing information. Routes to the
calibration-triage queue — the operator's response is "investigate the
engine/register," not "decide the case."

## 2. The escalation payload — the operator's seven sections

ONE payload serves act-cases AND decline-cases.

**A — What happened**: A1 the headline (length-bounded, rendered as the
operator will see it); A2 claim-vs-evidence, never one narrative; A3
who-else-is-on-it (the M1 dedup state).

**B — What I want to do**: B1 the concrete change; B2 the surface + the
audience visibility; B3 the site + the criticality + the tier (from the
capture record); B4 the timing collisions (M7).

**C — What I tried**: C1 the attempt log with outcome evidence; C2 the
declines stated as such, first-class (M3).

**D — What it costs**: D1 the blast radius + the duration + the
resources; D2 the cost-of-NOT-acting (do-nothing is a first-class option);
D3 what-my-verification-cannot-see (the M4 honesty line).

**E — Alternatives**: E1 considered, with why-not, including do-nothing
and escalate-now-act-later; E2 the recommendation + the confidence + what
would change it.

**F — The reversibility line (mandatory)**: F1 the agent's claimed undo
PATH (concrete, falsifiable, never a boolean); F2 the Corvus class verdict
(the table overrides the agent; unknown = destructive); F3 the operator
confirm-or-correct on destructive/unknown classes — every correction
writes a class-table row.

**G — The ask**: G1 options-with-consequences, never bare yes/no; G2 the
expiry + the conservative default; G3 answerable in place, lands back in
the record.

**The field-source contract**: the capture-record spine (decision_id,
state hash, site, timing, tier, criticality, incident linkage) —
Corvus-computed; the agent-only honesty surface (the counter-evidence,
the attempt log including declines, the cost estimates, the alternatives,
the D3 line, the F1 path) — agent-narrative, provenance-labeled; the
Corvus-computed bridge (A3 dedup, B4 window, D1 cross-check, F2 verdict).
The narrative-vs-capture-trail disagreement is a credibility signal
feeding T1.

## 3. The decision packet (the scientist's formalization, six components)

1. **The question in decision form** — the site's W5 well-posedness
   restated for the human; the escalation's quality is bounded by the
   site's well-posedness (the escalation layer cannot repair the register).
2. **The decision-relevant evidence, provenance-stamped, unknowns
   explicit** — the R-SEC-16 frozen fact VALUES the decision turns on,
   each stamped (fresh / stale-within-tolerance / unknown); what the
   engine could NOT establish displayed as prominently as what it did;
   evidence-lane artifacts referenced with their uncertainty, never as
   facts.
3. **The engine's own answer + band, labeled** — the four-field verdict,
   shown below the evidence; the observe→enforce ramp REQUIRES the human
   to see the engine's answers; hiding them demotes the human from
   executive to raw sensor.
4. **The options framed as consequence-bearing actions** — the site's
   enum translated into actions; if the enum cannot be translated into
   actions the human can take, the enum is wrong (the W2 test at the
   escalation layer).
5. **The declared default and deadline** — the deadman fires the
   registered fail answer; not responding IS an unknown and lands in the
   same branch (the no-softer-path rule extended to the human loop);
   deadman-fired = the fail answer executed with provenance
   `escalation:deadman`.
6. **The frozen packet** — the payload freezes its facts, the engine
   answer, and the band AT MINT TIME; the human decides against the same
   frozen state the engine decided against, or the feedback loop measures
   noise.

## 4. The escalation as a registered site

The operator's response passes the boundary test on all four counts → it
registers. **Type: choice; solver: HUMAN — the fourth solver class.** The
machinery treats the human uniformly: the typed answer (enum-bound; free
text is an annotation, never the answer), the provenance stamp
(`human_decided(operator)`), the conformance analog (the deadman test +
payload-completeness), the fail policy = the deadman default.

**The feedback loop — three channels, all first-class:**
1. *Execution*: the answer executes through the same machinery, joining
   the decision_id chain.
2. *Calibration*: the human-answer vs engine-answer pairs accumulate per
   site into an agreement-rate metric — evidence consumable by the trust
   rule as ONE attested input, never an autonomy criterion by itself
   (an engine tuning itself to its rater is the capture loop again).
3. *Register repair*: PATTERNED human overrides are the empirical test of
   the site's thresholds — the escalation system is not a safety valve;
   it is the register's self-repair mechanism.

**The delivery grammar (complete)**: recorded → queued → delivered →
**answered** (the terminal decision state, keyed by escalation_id,
carrying the human's typed answer + provenance + response latency) →
deadman-fired (when no answer lands). The escalation_id is the join key
for all three feedback channels, exactly as decision_id is for the
outcome joins.

## 5. The security guarantees riding the payload

The refusals join the R-SEC-10 hash chain (deletable refusals would hide
the fingerprint of probing); the refusal stream doubles as the R-SEC-8
quarantine sensor; every escalation carries the human-surface SLO (did it
reach a human — measurable, alarmed); the payload's stamps are what the
enforce-flip gate audits.
