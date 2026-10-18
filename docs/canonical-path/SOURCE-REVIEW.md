# Corvus Source Review — the component verdicts

**Reviewed**: the full repo at eb2bb6f (2026-05-09, the last push), all five
components, read at source. Every verdict names what it read. The stance: the
source is an IDEA built over a year ago while learning the tools — the concepts
are judged on their merits, the implementations on today's needs, and the
product-first target (other agent fleets from day one) is the lens.

## The headline

**The idea is right and bigger than the code shows.** The product concept — a
shared operational picture for agent fleets, with structured events, pre-action
conflict checks, and trust-graded autonomy — is exactly the outcome the
operator names (the CCB / IR command center). The implementation proves the
concept works (it ran, with real agent consumers) but carries year-old
decisions and one large unbuilt ambition. The canonical path is: keep the
concept spine, rebuild the core against today's shape, kill what never
shipped, and finish the hooks story for the harnesses that actually exist now.

## corvus-server (the core)

### The shared state model — VERDICT: EVOLVE

**Read**: `corvus-server/src/database.py:19-193` — ten tables (ops_changes,
ops_events, ops_incidents, ops_problems, ops_cmdb, ops_ci, ops_audit_log,
ops_triage_log, ops_pending_steps, ops_knowledge); `src/routers/` — 28 routers,
117 routes.

**What the idea got right**: the state model is the CCB's spine and it is
correct — changes (with targets, rollback plans, expiry, authentication),
events (with the full relationship graph: related_incident/change/problem,
parent_event, signature), incidents, problems, the CMDB, and knowledge. The
separation of changes from incidents from problems is real ITSM discipline.

**What is stale**: the mesh-federation columns (node_id, hlc_timestamp,
mesh_sync_status, synced_peers on every table, database.py:33-34, 47-52) serve
a federation that was never built (see the mesh verdict below). They are dead
weight in every query. The `targets` JSON-array with `LIKE '%target%'`
matching (routers/events.py:281-285) is the fragile spot: string-subset
matching on a JSON blob is the conflict check's foundation and it can
false-positive (the target `web` matches `webhook-service`) and
false-negative (the array order matters).

### The event protocol — VERDICT: KEEP (the idea), EVOLVE (the implementation)

**Read**: `src/ocsf.py` (the OCSF 1.3.0 class map), `src/models/events.py:11-50`
(the EVENT_TYPE_ALLOWLIST, ~25 types), `src/event_signing.py` (the HMAC-SHA256
signing, GAP-8), `src/routers/events.py:194` (the SSE stream).

**What the idea got right**: OCSF-native events are the correct
product-first decision — SIEM-portable, vendor-neutral, and the differentiator
versus every homebrew event log. The type vocabulary is well-designed
(the change/incident lifecycles, remediation, sweeps, LLM investigations,
actions, sessions, auth observability, sentinel probes). The HMAC signing and
the SSE stream are both right.

**What is stale**: the allowlist is a hardcoded frozenset — every new event
type is a code change and a redeploy, which for a product serving other fleets
is a release tax on the customers' vocabulary. The canonical path: the event
schema stays strict (the OCSF classes), the type registry becomes data
(the fleet-configurable vocabulary with the server-side validation), and the
signing keys become per-fleet.

### The conflict check (GO/CAUTION/STOP) — VERDICT: KEEP, sharpen

**Read**: `src/routers/events.py:271-389` — the consolidated target status:
the active changes + the active incidents + the recent events → the
recommendation, with the incident severity driving STOP and the
change+incident combination driving STOP.

**What the idea got right**: this is the CCB's core decision and the logic is
sound — the severity ladder, the combination escalation, the action-type
refinement (Phase 2). The hooks consume exactly this.

**What needs sharpening**: the target matching (the LIKE query above), and the
trust-tier lookup that follows (routers/events.py:336+) reads the CMDB's
service_type to grade the recommendation — the coupling is right but the
grade is opaque at the call site. The canonical path: the conflict check
becomes the first-class capability (the `/ops/conflict-check` contract with
the explicit inputs: the target, the action_type, the actor, the fleet) —
the product's most defensible surface.

### The trust ledger — VERDICT: KEEP (the idea), REBUILD (the model)

**Read**: `src/routers/trust.py`, `src/database.py:335` (the default
ESCALATE), `src/mcp_server.py:440-470` (the plan approval: all AUTO/SUPERVISED
auto-approves, any ESCALATE returns needs_approval, force= the human
override).

**What the idea got right**: the autonomy model — per-action-type trust tiers
with the plan-level gating and the human override — is the product's most
valuable concept. No comparable tool grades agent autonomy by action type.

**What is stale**: the tier vocabulary (AUTO/SUPERVISED/ESCALATE) has no
promotion/demotion mechanics visible in the routers (the README promises
"promote/demote autonomy based on outcomes" — the outcome-driven promotion is
aspirational), and the tiers are stored per action_type globally, not per
agent. For a multi-fleet product, trust is per (fleet, agent, action_type).

### The mesh federation — VERDICT: KILL (the ambition), SALVAGE (the HLC)

**Read**: `src/hlc.py` (174 lines, a complete Hybrid Logical Clock with the
causal ordering and the node tie-breaker), `src/mesh/` (contains ONLY
`__init__.py` — zero implementation), the mesh columns on every table.

**The verdict**: the federation was the ambition that consumed schema design
(every table carries the sync columns) and shipped nothing — `src/mesh/` is
empty. KILL the federation as a product goal (a multi-node conflict-free
replicated ops ledger is a research project, not a product feature).
SALVAGE the HLC: the timestamp quality (globally unique, causally ordered)
is valuable even single-node (the event ordering across agents), and the
implementation is clean. The schema's mesh columns go in the rebuild.

### The FMEA runbooks — VERDICT: EVOLVE

**Read**: `corvus-server/runbooks/` — the triage runbooks for 8+ service types
(automation, database, deploy, dns, home-automation, inference, iot-gateway,
mcp-bridge); the working tree shows 2 deleted (caipe_agent, caipe_supervisor —
the integration-specific pair). `src/routers/runbooks.py` +
`triage_router` serve them.

**What the idea got right**: service-type-aware triage (the failure modes per
service class, the investigation steps per failure) is a genuine
differentiator — the agents don't just see that something broke, they get the
service-class-appropriate investigation plan. The YAML runbooks are data
(extensible without code).

**What is stale**: the two deleted runbooks signal the integration-specific
content rotted; the runbook format and the trigger conditions need the
canonical definition (what makes a runbook trustworthy enough for an agent to
follow?). EVOLVE with a schema and a validation gate.

### The MCP integration — VERDICT: KEEP

**Read**: `src/mcp_endpoint.py` (980 lines: the embedded MCP server over SSE
at /mcp/sse, the httpx ASGITransport for the zero-overhead internal calls),
`src/mcp_server.py` (630 lines: the ops tools as MCP tools — the plan
approval, the execution, the state queries).

**What the idea got right**: exposing Corvus as an MCP server is exactly how
agents consume a service in 2026 — the harness-native protocol, no custom
SDK required. The internal-call design (ASGITransport) is clean. This is the
product's consumption surface and it aged WELL.

### Discovery/CMDB automation — VERDICT: EVOLVE

**Read**: `src/discovery/` (collector.py, container_inspector.py, declared.py,
deploy_manager.py, graph_utils.py) + `src/graph.py` (the Neo4j dependency
graph, 437 lines).

**What the idea got right**: the CMDB that populates itself (the container
inspection, the declared-vs-discovered reconciliation) is the awareness
foundation — the conflict check and the blast-radius queries need it.
The Neo4j dependency graph (the blast radius, the dependency chains) is the
IR command center's map.

**What is stale**: Neo4j as a hard dependency for the core (a separate
database for the graph) is a deployment tax; the graph queries the product
actually serves (the blast radius, the dependency chain) fit a lighter model
(the relational adjacency or the embedded graph). The discovery collectors
are Docker-specific.

## corvus-hooks — VERDICT: EVOLVE (and finish)

**Read**: `corvus-hooks/corvus-governance.py` (the Claude Code PreToolUse
hook: intercepts the Bash/destructive-MCP calls, extracts the target, checks
the server, exit 2 blocks; fail-open when unreachable),
`corvus-hooks/adapters/` (cline_hooks.py, codex_hooks.py, windsurf_hooks.py —
three adapters, thin), the README's ten-tool table.

**What the idea got right**: harness-level enforcement outside the model's
control (the hook intercepts before the tool runs) is the correct enforcement
point — the same conclusion the HQG governance stack reached independently.
Fail-open on unreachability is the right availability trade.

**What is stale**: the README claims ten tools; the adapters directory has
three, and they are thin. More importantly, the harness landscape changed:
DSH, OMP, and Pi are the operator's harnesses (with their own hook/extension
systems), and the product-first claim needs the hooks story to be REAL for
the harnesses agents actually use. The canonical path: the hook contract
(the stdin JSON → the conflict check → the exit-code decision) is the
product's enforcement SDK; the adapters are per-harness shims over ONE
contract, and the contract gets a conformance suite.

## corvus-cli — VERDICT: KEEP, thin

**Read**: `corvus-cli/src/corvus_cli/` (config.py, main.py; ~1004 lines across
the CLI+SDK).

The audit CLI (corvus_watch_events) is the auditor's surface and the README's
evidence-chain promise. Thin but functional. KEEP; the canonical path extends
it (the fleet filter, the evidence export).

## corvus-sdk + corvus-splunk — VERDICT: EVOLVE / KEEP

**Read**: `corvus-sdk/src/corvus_sdk/` (client.py, models.py), `corvus-splunk/`
(bin, default, lookups, metadata — the Splunk app structure).

The SDK is the typed client (the Python-only gap: the product-first claim
wants the HTTP contract to BE the SDK — any language speaks it). The Splunk
app consumes the OCSF forwarding — the SIEM story's proof. KEEP the Splunk
app; EVOLVE the SDK into the documented HTTP contract.

## The verdict summary

| Component | Verdict | The one-line reason |
|---|---|---|
| The shared state model | EVOLVE | The spine is right; the mesh columns are dead weight, the target matching is fragile |
| The event protocol (OCSF) | KEEP / EVOLVE | The differentiator is right; the hardcoded allowlist is a release tax |
| The conflict check | KEEP, sharpen | The CCB's core decision; make it the first-class contract |
| The trust ledger | KEEP / REBUILD the model | The autonomy model is the most valuable concept; per-fleet/per-agent trust is the product shape |
| The mesh federation | KILL / SALVAGE the HLC | Never shipped; the schema carried its cost; the timestamp quality survives |
| The FMEA runbooks | EVOLVE | A real differentiator; needs a schema and a validation gate |
| The MCP integration | KEEP | The consumption surface, aged well |
| Discovery/CMDB | EVOLVE | The awareness foundation; de-tax the graph dependency |
| The hooks | EVOLVE, finish | The right enforcement point; the ten-tool claim needs the real adapters over one contract |
| The CLI | KEEP | The auditor's surface |
| The SDK | EVOLVE | The HTTP contract IS the SDK |
| The Splunk app | KEEP | The SIEM story's proof |

## What the canonical path must decide (the input to the ADRs)

1. **The deployment shape**: single-binary embedded (SQLite) vs multi-tenant
   service (the fleet isolation) — the product-first claim forces the
   multi-fleet answer; the old code is single-tenant.
2. **The event vocabulary**: strict-code vs data-driven registry.
3. **The trust model**: the per-(fleet, agent, action_type) shape and the
   outcome-driven promotion mechanics.
4. **The hooks contract**: one enforcement SDK, the per-harness adapters, the
   conformance suite.
5. **The graph**: Neo4j vs the lighter dependency model.
6. **The relationship to the operator's HQG stack**: the gates and Corvus
   overlap (the pre-action enforcement, the event emission) — the CCB/IR
   framing says the gates FEED Corvus, not parallel it.
