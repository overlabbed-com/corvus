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
