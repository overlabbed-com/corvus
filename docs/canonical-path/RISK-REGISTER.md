# Corvus Project Risk Register

**Discipline**: revisited at every phase gate (the gate re-reads this
register per BUILD-PLAN's gate discipline). One page. No timeframes —
the triggers and mitigations are the content.

| # | Risk | Trigger | Mitigation | Re-assessed at |
|---|---|---|---|---|
| 1 | **Scope creep** — the ideation produced a large surface; the build could balloon trying to build all of it | A work package's scope grows past its DoD; new packages appear mid-phase | The WBS is the contract: new work enters as a NEW package with a DoD, never as scope-growth inside one; the capability gate is the phase's only exit | Every gate |
| 2 | **The design-perfectionism trap** — the googleplex-on-the-plan directive has a failure mode: never building | The go-package completes and the go still doesn't come; more planning artifacts appear | The go-package is DESIGNED to make the go cheap: the transition plan, the WBS, the dependency statement, and the spikes answer the questions a go needs; the spikes bound further planning ("the numbers are measured — plan less") | The go decision |
| 3 | **The model dependency** — clef-flash is one engine on one card (dp01) | The engine is down or degraded; the co-tenant pressure | The designed mitigation IS the answer: the fail-policy floor (the autonomy drops to CAUTION/ESCALATE), the escalation queue's SLA + deadman, the observe-mode attempt records making it visible; the estate's engine-rollback patterns (park, not delete) apply | P1 exit; any engine incident |
| 4 | **The solo-builder bottleneck** — one builder serializes the WBS | The parallel tracks (the engine-side, the Corvus-side) stall on one actor | The WBS's parallel tracks are team-delegation-shaped (the disjoint scopes, the shared tasks); the agent-team patterns apply when the build starts | P1 start |
| 5 | **The v1-cutover risk** — the revival touches the estate's running surface | The k8s deployment or the adapter install misfires | The transition plan's rollback story: GitOps revert + the registry-side pin for the deployment; the adapter's registration removal for the hooks; the rollback target is the 5-month status quo | The deployment step |
| 6 | **Spec drift** — the build diverges from the design silently | An implementation choice contradicts an artifact without the amendment path | The design-change process (amend → ledger → survival test → traceability); the survival test re-run at every gate; the WBS's DoD checks are the drift detectors | Every gate |
| 7 | **The register-sweep blocking** — WP0's [S] dispositions stall on judgment calls | A sweep item lacks a clear recorded basis | The dossier's [S] marks name what's under-determined; the sweep decides with the recorded evidence + the operator's steer; no sweep item blocks the engine-side packages (WP1-WP8) — only the criteria-content consumers | P1 start |
| 8 | **The governance-gap length** — the estate runs ungoverned until P1's observe mode | The go delays; the build stalls | The manual discipline (CHECKPOINTs) held for ~5 months and remains the fallback; the transition plan's rollback target IS that status quo; the go-package exists to shorten the gap | Every gate |

**The register's honest framing**: risks 2 and 8 pull in opposite
directions (build too late vs build too early) — the resolution is the
same artifact: the go-package makes the informed go cheap, and the WBS
makes the build bounded. The gate structure exists precisely to hold
that tension.
