# Corvus — the Product Definition (canonical)

**What Corvus is**: the change control board and incident response command
center for agent fleets. When your agents are the IT workers executing change,
Corvus is the CCB they check before acting, the shared picture they all see,
and the evidence chain your auditor reads afterwards.

**The operator's definition (2026-10-18, quoted)**: Corvus is the product —
operational awareness for agents; environment awareness for agents; it
connects agents together for that shared awareness; it tracks when things are
broken. If your agents are your IT workers that are executing change, Corvus
is your change control board, it's your IR command center.

**The four capabilities** (the product's surface, in order of value):

1. **Change control** — the pre-action check: before an agent touches a
   target, Corvus answers GO / CAUTION / STOP from the active changes,
   incidents, and trust on that target. This is the product's most defensible
   surface and the hooks' core call.
2. **Shared awareness** — the structured event stream (OCSF 1.3.0) every agent
   in the fleet emits to and reads from. One agent's action is every other
   agent's context. The SSE stream is the live fabric; the query API is the
   historical record.
3. **Graded autonomy** — the trust ledger: per (fleet, agent, action_type)
   tiers that decide what an agent may do unsupervised. The outcome events
   feed the tiers; the tier changes are themselves auditable events.
4. **Breakage tracking** — incidents, problems, and the service-type FMEA
   runbooks: when something breaks, the right investigation fires and the
   failure-mode knowledge compounds.

**What Corvus is not**: not a monitoring system (the metrics/alerting stack
feeds it — it consumes, it does not scrape), not a secrets store, not a
workflow engine, not the agent harness. The enforcement stays at the harness
level (the hooks/gates); Corvus is the awareness and decision service they
consult and report into.

**Who it is for**: any fleet of agents executing change on shared
infrastructure — deployed self-hosted per fleet, consumed by agents over MCP
and HTTP, forwarded to the fleet's SIEM. The homelab estate is one deployment;
nothing in the core knows that.

---

# The Product Lens (ideation phase, 2026-10-18)

**Source**: the product-strategist's four-chunk arc, consolidated.

## The customer segmentation (three buyers)

1. **Adopters** — the engineers whose daily work is agents executing change;
   they feel the pain (the silent decline, the wrong-cause alert, the wedged
   lane) and want the brake pedal.
2. **Payers** — the managers/leaders who own the risk, the budget, and the
   audit; they buy governance, evidence, and compliance posture.
3. **Multipliers** — the consultancies/SIs who productize client-proven
   patterns; they extend the marketplace and align with revenue share.

## The wedge (the minimum viable entry)

C1 alone — the agent brake pedal: the pre-action conflict check + the
adapter + the decision ledger + the observe→enforce ramp. "The brake pedal
ships with the flight recorder": the record schema is day-one wedge scope;
the flip gate (three evidence-based criteria computed from the observe-era
records) is the enterprise feature hiding in Tier 0. "Observe fills the
meter; enforce mode spends it."

## The pricing (two-axis, assurance-not-features)

**Axis 1 (usage)**: per active fleet. **Axis 2 (assurance)**: quotable-cell
coverage — the fail-policy matrix as the SLA table, generated from the
signed register (never hand-copied); the tier table quotes only
proof-backed cells; the assurance axis grows with proven cells, not
designed ones; the page shows the denominator ("N of M cells provable
today"). Tier 0 promises the basic cells; Tier 1 the full matrix plus the
delivery chains; Tier 2 isolation plus provable runs (the conformance-run
evidence export — the SOC2/ISO artifact).

## The marketplace (the third moat layer)

Four supply layers: builtin/ (first-party, immutable per register version)
→ first-party packs (verticals) → publisher packs (the multipliers) →
org-private packs (Tier 2 policy-as-code). Three defensible mechanics:
outcome-weighted ranking (downloads lie, outcomes don't; the pack contract
requires an outcome_binding with exact decision-id joins — coarse joins are
diagnostic-only), certification = enforcement rights (uncertified packs run
observe-only), three-state transparency on every pack page. The ratchet:
promises only ratchet toward safety — at the register (downgrade events),
the compiler (tightening-only org overrides), the marketplace
(certification gates enforcement).

## Trust as a product

Corvus doesn't sell trust; it sells the evidence that makes trust auditable
and the revocation that makes it safe to grant. Four surfaces (all
projections of the record store): the Trust Map, the Promotion Queue (the
readiness meter as a grid with the named binding constraint), the Audit
Trail, the Benchmark. The liability shape: procedural, not outcome-based —
the driver's-license model. **The ledger is the defense, the preconditions
are the duty of care, the demotion is the response, the process promise is
the boundary.**

## The boundaries (the negative-space definition)

Eight nots: not the monitor · not the secret store (credential-blind — a
compliance selling point) · not the harness (the adapter stays thin on
purpose) · not the executor · not the identity provider · not the human
change calendar (upstream state consumed, never replaced — ServiceNow is a
source system whose customers are our buyers) · not the agent's task
reasoning · not the GRC system of record. Three edges: the adapter edge
(inbound control), the state edge (read-only ingestion), the emission edge
(outbound exports). **The growth rule: Corvus grows by adding vocabulary
and edges, never by owning new planes.**

## The partnerships (priority-ordered)

1. Harness vendors (adapter certification — the channel) · 2. The ITSM
incumbents (the change-calendar-in / change-record-out integration — the
highest-value S2 unlock) · 3. Cyber insurance (co-defining the
autonomy-governance evidence standard; Corvus underwrites nothing) · 4.
Executor/runbook platforms · 5. Observability sources (marketplace source
packs) · 6. Escalation (PagerDuty, Slack — the E2 delivery chains).

## The commercial boundary

Corvus promises the process — gates, records, evidence, revocation — and
never the outcome. No "your agent won't break prod." The tier table's cells
are the complete promise surface; anything not a quotable cell is not a
promise. Records stay exportable — the lock-in is the running governance,
the benchmark position, and the operational muscle memory, never hostage
data.
