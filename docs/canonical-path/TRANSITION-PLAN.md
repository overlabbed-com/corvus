# Corvus Transition Plan — v1 → v2

**The premise correction (this plan's most important finding):** the
lifecycle review assumed "V1 is running." It is not. **V1 Corvus was
deliberately decommissioned on 2026-05-28** per a planned, checkpointed
decommission (`~/repos/wt-homelab-k3s-docs-cascade/docs/plans/
corvus-decommission.md`, executed per Task 1.3 and the phases that
followed), preserve-don't-delete. The dockp04 containers exited that day;
the hooks were archived (`~/.claude/hooks/_archive-corvus-decom-2026-05-28/`);
the data was snapshotted. The estate has run **without centralized
governance for ~5 months** — per decommission decision D-6, agents fell
back to explicit pre-action risk classification + Todd CHECKPOINTs, and
OpsLite (the admin-api ops_* tools) survived standalone for ad-hoc
tracking.

**So the transition is not a cutover of a live system. It is the revival
of governance as v2, with v1 as a preserved, analyzable predecessor.**
Every question below is answered against the inspected reality, not the
assumed one.

## The inspected v1 state (evidence, 2026-10-19)

- **Containers**: `dockp04-corvus-corvus-1` (localhost:5000/corvus:latest)
  Exited(0) and `dockp04-corvus-corvus-neo4j-1` (neo4j:5-community)
  Exited(137), both since ~2026-05-28 — stopped, not removed.
- **Data volumes** (docker named, on dockp04, all preserved):
  `dockp04-corvus_corvus-data` (175M — the SQLite ops DB + audit JSONL) ·
  `dockp04-corvus_corvus-neo4j-data` + `dockp04-corvus_neo4j-data` (the
  CMDB graph, ~750K) · `corvus-data` (104K, the earlier standalone
  deploy) · `dockp04-corvus-test_*` (3M, a test deploy) ·
  `dockp04-corvus_registry-data` (the local registry — belongs to the
  compose stack's separate local-registry service, not Corvus itself).
- **Snapshots** (decommission D-2/D-3, executed 2026-05-28):
  `/mnt/media/archive/corvus-snapshot-2026-05-28/` — `corvus.db` (636M),
  `neo4j.dump` (17K), `dot-env.bak`.
- **Hooks**: archived 2026-05-28 — the CC hook chain (5 registrations),
  the adapters (cline, codex, windsurf), the Augment rule doc, the
  installer; the restore path documented in the archive README (move back
  + re-add registrations from the `.pre-corvus-decom` settings backup).
  Current `~/.claude/settings.json` contains **zero** Corvus references.
- **Code**: v1 is pinned at the `v1-archive` split (PR #42); main carries
  the v2 spine. The last v1-era work was PR #39 (the CAIPE service types
  + runbooks).
- **K8s**: v1's manifests were STAGED but never deployed
  (`k8s/apps/corvus/` in the homelab-k3s repo, commented out in the
  kustomization) — the single-container v1 shape, obsolete for v2's
  two-service architecture.
- **Credentials**: the keychain query found no `corvus.*` entries
  (either cleaned post-decom or never present on this Mac — verification
  is a checklist item); the decommission plan's Phase 2 (the Keycloak
  `corvus-*` clients, the 1Password items) completion state unverified.

## Q(a) — Coexist or cutover? **Neither: staged revival.**

V1 is stopped; there is nothing to coexist with and nothing to cut over
from. The real decision is the **revival sequencing**, and it follows the
build plan's wedge:

1. The contract spike validates the wire shape (pre-go).
2. The P1 build (on the operator's go).
3. The engine + Corvus deploy to k8s — **fresh v2 manifests** (the two-
   service architecture per ENGINE-DESIGN.md; the staged v1 manifests are
   a reference, not a base).
4. The Claude Code adapter ships — the first governance restoration
   (CC was the primary consumer per the archive).
5. The observe-mode period; the flip gate's criteria accrue.
6. The enforce flip; then the other tools per demand.

**Why not revive v1 as a stopgap**: v1 lacks the decision engine —
reviving it restores the OLD governance and creates a second cutover
later, doubling the migration work. The estate has run ~5 months
ungoverned; a few more weeks to P1 is tolerable, and the manual
discipline (CHECKPOINTs) demonstrably held. The revival risk is a bad
adapter, not the wait — so the adapter ships only after the contract
spike and the observe-mode period, not before.

**The gap accounting** (the plan's risk framing): ~5 months of agent
operations ran without the centralized gate. No documented ungoverned
incident surfaced in this session's evidence — the manual discipline
carried — but the window is real and the P1 wedge is what closes it. The
transition plan's urgency is bounded by that honest statement.

## Q(b) — V1's event history: **archive read-only; start clean; carry the reusable assets.**

V1's history contains **no decision-engine records** (v1 had no engine —
its event/audit history has no `request_hash` join, no verdicts, no
probabilities), so its training-corpus value is bounded. V2's decision
records, capture store, and training corpus **start clean**. What IS
worth carrying:

- **The 12 FMEA runbooks** (in the repo, `corvus-server/runbooks/`) —
  carried forward as v2 content (the triage knowledge is engine-
  independent).
- **The CMDB graph** (the `neo4j.dump`, 17K) — the service topology as
  seed data for v2's state layer, if the v2 state model wants the
  relationships (a P1-scoping decision, not a blocker).
- **The OCSF event history** — already forwarded to the SIEM before the
  decom; the estate's lakehouse retains it. No v2 action needed.
- **The 636M `corvus.db` snapshot** — preserved read-only at the archive
  path for analysis (the ops history, the incident records). Not ingested.

The live volumes stay on dockp04 under the decommission's D-5/D-7 gates
(the 90-day sweep for the backup dir was Todd-review-gated; the volume
disposition waits for v2's data model to finish deciding what's worth
carrying). **Nothing is deleted by this transition.**

## Q(c) — The hooks' replacement: **per-tool, Claude Code first.**

The archive IS the integration inventory: CC's 5 hook registrations (the
PreToolUse governance ×2, the UserPromptSubmit lifecycle, the PostToolUse
emit ×2), the shared `corvus_core.py`, the standalone adapters
(cline/codex/windsurf), the Augment rule doc, and the pi-config
extensions — of which `pi-mac-governance`'s `evaluateCorvusFirst()` was
the deepest integration (it **blocked tool execution on DENY**).

V2's adapter replaces the hooks per the three-edges model (the adapter
edge: interception, the typed ask/answer, the outcome emission) — the
v1 hooks are NOT restored; their archive documents the integration
surface v2 must cover. The revival order:

1. **Claude Code first** (the primary harness; the estate's daily driver).
2. **pi-mac-governance second** — it needs a v2-aware
   `evaluateCorvusFirst()` (the verdict-token consume path) or an
   explicit retirement decision; its post-decom state needs verification
   (the decommission plan flagged its failure mode as a precondition).
3. **The other-tool adapters last** (cline/codex/windsurf), demand-driven
   — the v2 adapter contract makes each a small port.

## Q(d) — V1's death: **already executed; what remains is disposition.**

The decommission happened 2026-05-28. The remaining disposition
checklist (each verifiable, none blocking v2):

- [ ] The credential cleanup verification: the keychain entries (not
  found in this check — confirm cleaned vs pending), the 1Password items
  (`services/dockp04-corvus-secrets`, `k8s-corvus-oidc-keycloak`,
  `services/corvus`), the Keycloak `corvus-*` clients (Phase 2 of the
  decommission plan — executed?).
- [ ] The D-5 90-day sweep: `/mnt/docker/corvus-neo4j-backups` on dockp04
  (the calendar reminder from Task 5.8 — fired? swept?).
- [ ] The volume disposition: the seven corvus-related volumes stay
  preserved until v2's data model decides (D-7's Todd-review gate).
- [ ] The docs tombstones: the governance.md authority section (D-6
  removal — done), the obsolete plan docs (ws-13-corvus, the migration-
  strategy WS-13 entry — marked obsolete per the decommission plan).
- [ ] The ghcr image: `ghcr.io/overlabbed-com/corvus:latest` (the v1
  image) — leave; v2 ships its own tags.

## The rollback story (per revival step)

- The **contract spike**: throwaway; nothing to roll back.
- The **k8s deployment**: GitOps revert + the registry-side pin (the
  estate's image-rollback reality — the pin is the durable lever).
- The **adapter rollout**: remove the hooks registration (the
  `.pre-corvus-decom` backup pattern documents the mechanics); the agents
  fall back to the D-6 manual discipline, which is the current steady
  state — **the rollback target is the status quo the estate has lived
  for 5 months.**
- The **data**: v2's stores start clean and append-only; nothing to roll
  back.
- Every deployment change: GitOps-only, the homelab-k3s delivery
  patterns, the DDR where the tier/deny-path requires.

## The transition's success criteria

1. V2's P1 wedge deploys and restores CC governance (the observe mode
   first) — the governance gap closes.
2. The revival is stepwise and reversible at every step (the rollback
   story above).
3. V1's preserved state (the volumes, the snapshots, the archive) remains
   intact until its disposition decisions are made — nothing deleted.
4. The disposition checklist above completes before the volumes' final
   disposition.
