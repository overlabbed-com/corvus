# The Corvus Decision Register — every decision, enumerated

**Schema version**: 1. **Status**: authoritative. **The gate rule** (see the
bottom): a new decision ships only with a register entry — the adversarial
review enforces it.

Corvus's decisions are typed sites for the estate's decision-engine lineage
(the stuntd/clef-decide contract): state in, typed sites (choice | score |
noul), typed answers out with per-option probabilities, fail-closed at both
ends. This register enumerates every site — the machine-readable data lives
beside this document (`decision-register.yaml`); this document is the
human-readable index and the gate rule.

## The sweep method

Two passes, both recorded per site:
1. **The code pass**: every branch point in the v2 core that selects an
   outcome (the `if`-ladders producing recommendations, the validation
   raises, the tier reads) — each gets file:line.
2. **The design pass**: every decision the canonical design implies that the
   v2 code hasn't grown yet (the ADR-003 trust mechanics, the plan gating,
   the incident triage, the runbook matching) — each cites its ADR or the
   PRODUCT capability.

The gap pass: the four capabilities walked against the register — any
capability decision missing from the register is a sweep defect.

## The site families

### Family C — change control (live in v2)

| Site | Question | Type | Outputs | Fail policy | Source |
|---|---|---|---|---|---|
| C1 | May the actor proceed on this target right now? | choice | GO, CAUTION, STOP | fail-closed → CAUTION (the safe default when the engine is unreachable) | core.py:120-156 |
| C2 | Is the target carrying an active critical condition? | score | 0..1 (the criticality weight) | fail-open → the local severity heuristic | core.py:138 |

### Family T — trust (ADR-003, the P1 build)

| Site | Question | Type | Outputs | Fail policy | Source |
|---|---|---|---|---|---|
| T1 | Does this agent's outcome justify a tier promotion? | choice | promote, hold, demote | fail-closed → hold (the tier never moves on uncertainty) | ADR-003 |
| T2 | What trust tier applies to (agent, action_type) right now? | noul | the tier lookup (AUTO/SUPERVISED/ESCALATE) | fail-closed → ESCALATE | ADR-003, core.py:128-134 |

### Family P — plan gating (the design pass)

| Site | Question | Type | Outputs | Fail policy | Source |
|---|---|---|---|---|---|
| P1 | Does this plan step auto-approve or escalate? | choice | auto, escalate | fail-closed → escalate (the ESCALATE default) | ADR-003, the mcp_server.py:440-470 lineage |
| P2 | Is the plan safe to start given the current fleet state? | choice | yes, no | fail-closed → no | ADR-003 |

### Family I — incident triage (the design pass)

| Site | Question | Type | Outputs | Fail policy | Source |
|---|---|---|---|---|---|
| I1 | What severity does this event/incident carry? | choice | info, low, medium, high, critical | fail-open → the emitter's stated severity | the event model |
| I2 | Which FMEA runbook matches this service type? | choice | the runbook id, none | fail-closed → none (the generic investigation) | the FMEA capability |
| I3 | Is this incident a recurrence of a known problem? | noul | the matched problem id, or none | fail-open → none | the problems model |

### Family E — events (partially live)

| Site | Question | Type | Outputs | Fail policy | Source |
|---|---|---|---|---|---|
| E1 | Is this event type valid and in the fleet's vocabulary? | noul | valid, invalid (+ the reason) | fail-closed → invalid | config.py:43-45 |
| E2 | Does this event warrant escalation given the target's recent history? | choice | escalate, record | fail-open → record | the design pass |

### Family B — blind spots (the design pass)

| Site | Question | Type | Outputs | Fail policy | Source |
|---|---|---|---|---|---|
| B1 | What is the highest-value unknown to investigate next? | score | the ranked candidates | fail-open → the oldest unresolved | the README's blind-spot capability |

### Family W — change windows (the design pass)

| Site | Question | Type | Outputs | Fail policy | Source |
|---|---|---|---|---|---|
| W1 | Should this change window auto-expire now? | choice | expire, extend | fail-closed → expire (the auto_expire default) | core.py:94, the auto_expire field |

## The gap pass (the four capabilities walked)

- **Change control**: C1, C2, W1 — the family complete; the plan-gating
  handoff (P1, P2) covers the multi-step plans.
- **Shared awareness**: E1, E2 — the event validation live; the escalation
  classification designed. The gap noted: the SSE delivery ordering is not
  a decision (mechanical).
- **Graded autonomy**: T1, T2, P1, P2 — the family complete.
- **Breakage tracking**: I1, I2, I3, B1 — the family complete.

No capability decision is missing from the register. The next sweep re-runs
at each phase gate (the improvement loop).

## The gate rule

**A new decision ships only with a register entry.** The adversarial review
(and the code-review pass) checks every PR that adds a branch point
producing an outcome: if the branch is a DECISION (it selects among
meaningful outcomes for a consumer), the PR must add the site to
`decision-register.yaml` — the id, the question, the type, the outputs, the
fail policy, the source. A decision without a register entry fails the
review. The register is data-shaped so the engine integration reads it
directly.
