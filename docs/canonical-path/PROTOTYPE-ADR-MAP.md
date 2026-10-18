# The Prototype ↔ ADR Mapping (and the API contract)

The prototype (corvus-v2/) is the canonical path's proof. Each ADR maps to a
concrete behavior; the divergences from the old implementation are deliberate.

## The ADR → behavior map

| ADR | Decision | The prototype's behavior |
|---|---|---|
| ADR-001 | Self-hosted single binary per fleet; the fleet identity is configuration | `config.py` — the FleetConfig from the JSON file or the environment (CORVUS_FLEET_NAME/NODE_ID/API_KEY); `app.py` — one FastAPI app, the embedded SQLite, no external services |
| ADR-002 | The event vocabulary is data, the schema is code | `config.py` — the built-in lifecycle types + the fleet's custom_event_types (proven live: `deploy.canary` accepted, `not.a.type` → 400 with the valid list); the OCSF shape stays strict |
| ADR-003 | Trust per (agent, action_type); the tier changes are events | `state.py` — the ops_trust table keyed (agent, action_type), ESCALATE default; `core.py` — the conflict check reads the tier and escalates GO→CAUTION on ESCALATE; the tier-change events (`trust.promoted`/`trust.demoted`) are in the built-in vocabulary, ready for P1's mechanics |
| ADR-004 | One hook contract; adapters are shims | Not in the prototype's scope (P1) — the contract's server side (the conflict check) is the shape the hooks call |
| ADR-005 | The relational graph; Neo4j an export | Not in the prototype's scope (P2) — the spine carries no graph dependency (the proof: the prototype runs with zero external services) |
| ADR-007 | The spine without the mesh; exact target matching; the HLC | `state.py` — no mesh columns anywhere; the change_targets table (the normalized targets, exact matching); `hlc.py` — the thread-safe HLC (the salvage), every event's hlc_timestamp |
| (salvage) | The HMAC event signing | `core.py` — sign_event, the per-fleet key (the evidence chain's guarantee, salvaged from the old event_signing.py) |

## The deliberate divergences from the old implementation

1. **No mesh columns on any table** (the old schema carried them on every
   table for a federation that never shipped). The HLC survives as the event
   timestamp; the federation ambition does not.
2. **The targets are a normalized table** (change_targets) with exact
   matching, replacing the LIKE-on-JSON — the conflict check's correctness
   fix.
3. **The auth is the fleet API key** (X-Corvus-Key), not the OIDC/JWT stack
   the old code carried — the prototype's contract is the product's; the
   auth hardening is a deployment concern (P3).
4. **The trust table exists at the spine level** with ESCALATE defaults, so
   the conflict check's trust integration is live from day one — the old
   code bolted it into the router.

## The API contract (the product's surface — criterion 5)

- `GET /health` → `{status, fleet, node, event_types}` — the fleet identity
  is the deployment's config; the contract carries no estate-specific field.
- `POST /ops/events` `{type, target, source, severity, data}` → the ingested
  event (the HLC timestamp, the HMAC signature); 400 with the valid types on
  an unknown type.
- `GET /ops/events?target=&limit=` → the query.
- `GET /ops/events/stream` → the SSE live fabric.
- `POST /ops/changes` `{targets[], description, rollback_plan, ...}` → the
  change window.
- `GET /ops/changes/active?target=` → the active windows on a target.
- `GET /ops/conflict-check?target=&action_type=&actor=` →
  `{recommendation: GO|CAUTION|STOP, reasons[], active_changes[], trust_tier}`.
- Auth: `X-Corvus-Key` (the fleet's key). Content: JSON. No homelab-specific
  wiring anywhere — the contract is the product's (criterion 5).
