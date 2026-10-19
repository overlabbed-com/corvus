# Corvus v2 Operational Readiness — operating the service in the homelab

**Source**: the estate's discipline (GitOps, the ESO patterns, the deadmen,
the alert-delivery verdicts, the registry-side rollback) applied to the v2
architecture (the two-service deployment: the decision engine + Corvus).
The transition plan's revival sequencing is the deployment story; this
document is the operate story.

## The deployment shape

- **The namespace**: `corvus` (fresh — the v1 ran as a dockp04 Docker
  compose stack, outside k8s; the v1's staged manifests in
  `k8s/apps/corvus/` are a single-container reference, obsolete for the
  two-service shape).
- **The workloads**: `corvus-engine` (the decision engine per
  ENGINE-DESIGN's C0–C7) + `corvus` (the organization layer: the fact
  composer, the attested stores, the trust ledger, the verdict-token
  issuer). The engine is stateless-plus-capture (the three-store
  inventory); Corvus holds the attested stores (the PVC per the
  store-class table's evidence/telemetry split).
- **The GitOps wiring**: the homelab-k3s pattern — the manifests under
  `k8s/apps/corvus/`, the Kustomization entry, the ImageRepository +
  ImagePolicy pair (the `$imagepolicy` marker with a CONCRETE seed tag,
  never `:latest`), the Flux image-automation for the first-party builds.
- **The credentials**: the ESO patterns — the engine's API key via the
  ExternalSecret (the 1Password source), the CC adapter's key likewise;
  the Corvus↔engine channel rides the service identity (the v1-local
  posture: loopback/service-account; the mTLS promotion is the SaaS
  phase).

## The monitors + alerts (the deadmen)

| Signal | What it detects | The alert shape |
|---|---|---|
| The service down | The engine or Corvus unreachable | `up{job=~"corvus.*"} == 0` — the deadman (absence-based, fires on silence) |
| The capture ingestion live | The capture store stopped accepting (the spool wedged, the disk full) | The capture_dropped metric > 0, or the ingest liveness stale |
| The decision latency | The solve p99 breaching the budget | The per-site latency histogram vs the declared budget |
| The fail-policy application rate | The engine degraded (the fail policies firing at an anomalous rate) | The seam's budget-exhausted counter + the fail-policy application rate per fleet — the F11 detection signal |
| The escalation queue depth | The pauses accumulating (the C1-unavailable flood, the ESCALATE-fatigue) | The queue depth + the oldest-item age vs the SLA |
| The verdict-token anomalies | The enforcement seam misbehaving | The consume-refusal rate (the replay attempts, the expiry refusals) |

**The alert-delivery verification** (the estate's verdict discipline):
every alert above is verified to REACH A HUMAN — an alert that never
arrived is the silent-decline class (the incident-1 pattern). The
delivery path: the estate's Robusta front-door (the sole Slack notifier);
the delivery verdict checked per the homelab's alert-delivery-verdict
discipline, not assumed from the absence of log lines.

## The rollback

- The **image**: the registry-side pin is the durable lever (the estate's
  image-rollback reality — a git revert of the manifest does not roll the
  deploy; the pin does). The ImagePolicy's automation is suspended before
  a manual pin; restored after.
- The **adapter**: the CC adapter's registration removal (the
  `.pre-corvus-decom` backup pattern documents the mechanics); the
  rollback target is the D-6 manual discipline — the status quo the
  estate has lived since 2026-05-28.
- The **data**: v2's stores start clean and append-only; nothing to roll
  back. The snapshots (the v1 archive) stay untouched on dockp04.

## Who gets paged

The operator (Todd) — the homelab's single-human reality. The escalation
path: the Slack alert → the operator; the break-glass (the fail-closed
enforcement outage) follows the designed posture — the fleet's autonomy
drops to the fail-policy floor and the manual CHECKPOINT discipline
resumes, which is the D-6 status quo the estate already knows.

## The v1-coexistence monitoring

Per the transition plan: v1 is stopped (not removed); the coexistence
surface is the DATA (the preserved volumes + the snapshot archive), not a
running service. The only v1-coexistence monitoring: the disposition
checklist's items (the 90-day sweep, the credential cleanup) — tracked in
TRANSITION-PLAN.md, not monitored.

## The readiness gate

The service is operationally ready when: the deadmen fire correctly (each
alert proven able to fail — the mutation discipline), the alert-delivery
verdict is green for every alert, the rollback is exercised once (the
pin-flip drill on a non-production replica), and the runbook (this
document + the transition plan) survives the survival test.
