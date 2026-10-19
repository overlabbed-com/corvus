# The Decision Engine Contract — the seam Corvus speaks

**Version**: 1. **Lineage**: the estate's typed-decision contract
(clef-decide over stuntd/Jev) — no new vocabulary. **The placement**: the
engine is a separate lightweight service; Corvus (the stateful organization
layer) calls it over HTTP. Locally both run on one host; in the SaaS future
the engine scales independently and serves multiple fleets — which is why
every call carries the fleet id and the engine's state is fleet-scoped.

## The call

```
POST /v1/fleets/{fleet_id}/decide
Authorization: Bearer <the engine key>
Content-Type: application/json

{
  "state": { ...any JSON — the situation... },
  "sites": {
    "C1": {
      "type": "choice",
      "instructions": "May the actor proceed on this target right now?",
      "criteria": {"GO": "...", "CAUTION": "...", "STOP": "..."}
    }
  },
  "timeout_ms": 2000,
  "fail_policy": {"C1": "fail-closed:CAUTION"}
}
```

## The response

```
200 OK
{
  "answers": {
    "C1": {
      "answer": "CAUTION",
      "probabilities": {"GO": 0.1, "CAUTION": 0.7, "STOP": 0.2}
    }
  },
  "engine": {"id": "...", "latency_ms": 140}
}
```

## The fail-closed contract (BOTH ends)

- **The boundary**: a malformed site (the unknown type, the missing
  instructions, the criteria not matching the type) is rejected HERE —
  `400` with the contract message naming the site and the defect. It never
  reaches the engine core.
- **The answer**: an out-of-enum answer (the choice outside the criteria,
  the score outside the scale) is an **error** — `422` with the site and
  the offending value. The engine never guesses.
- **The transport**: Corvus applies the SITE's fail policy when the engine
  is unreachable or times out — the fail-closed sites use their registered
  `fail_default` (C1 → CAUTION); the fail-open sites use theirs. The
  timeout is per-call (default 2000ms).

## The SaaS seams (designed in, not retrofitted)

- The **fleet id** is in the path: every decision is fleet-scoped, and the
  engine's decision state (the learned weights, the capture store) is
  scoped per fleet.
- The **engine key** is per-deployment (the Corvus fleet ↔ the engine
  tenant); the local dev shares one key.
- The **engine is stateless per call** — the state arrives in the request;
  anything the engine learns (the capture store, the conformance data)
  persists under the fleet's scope.

## The conformance fixtures (the contract's proof)

1. The valid site → 200, the typed answer, the probabilities summing to 1
   for choice.
2. The malformed site (the unknown type) → 400, the contract message.
3. The out-of-enum answer (the engine returns an unlisted value) → 422.
4. The unreachable engine → the client applies the site's fail policy
   (the Corvus-side test, not the engine's).
