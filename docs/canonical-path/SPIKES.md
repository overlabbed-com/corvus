# Corvus Feasibility Spike Reports — the go-package's empirical evidence

**Discipline**: pre-go, exploratory, throwaway-by-default (the promotion
rule: spike code that becomes a package's seed enters the WBS). Each
spike: the measured numbers, the verdict, the findings.

## Spike (a) — The contract spike ✅ COMPLETE

**What ran**: the v2 spine's engine shim (the seed's contract
implementation) serving `/v1/fleets/{fleet_id}/decide`, exercised by the
conformance fixtures — extended this spike from 6 to 18 tests.

**The numbers**: 18/18 fixtures pass. The proven paths: the happy path
(the typed answers with the per-option probabilities summing to 1), the
400 paths (the malformed site, the choice without criteria, the
no-sites), the 422 path (the out-of-enum answer), the answers∪errors
invariant, the fail policy on unreachability (the degraded answer =
the registered default), **the existence-hiding** (the unknown fleet and
the known-but-unauthorized fleet → 404 with IDENTICAL bodies — the
R-SEC-5 rule, now fixture-proven), **the provenance-floor rejection**
(a fact below the declared minimum class → 400 with the structured
payload: failed_fact_id / required_provenance_class /
observed_provenance_class — the adversarial review's remediation,
now fixture-proven), the error envelope shape (`{"error": {...}}`).

**The findings (two, both fixed in the spike, both real design
confirmations)**:

1. **The shim's no-match default was PERMISSIVE.** The seed's heuristic
   defaulted to `options[0]` — which happened to be GO — on no signal
   match. The fail-conservative principle requires the opposite: the
   no-match fallback is the MOST CONSERVATIVE option (the conservative
   floor), never the first declared. Fixed in the spike; the principle
   lands in WP3's DoD (the dispatch's defaults fail conservative).
2. **The client conflated HTTP errors with unreachability.** The seed's
   DecisionClient caught `HTTPError` (a `URLError` subclass) in the
   unreachable-engine path — so a 400/404/422 from the engine would be
   MASKED as "engine unreachable" and the fail policy applied to a
   contract error. This is precisely the conflation the failure-mode
   column forbids (the fail policy's trigger is the BUDGET, not the
   error class — F1's rule). Fixed: HTTPError re-raises; only the true
   transport errors degrade. The finding lands in WP1's DoD (the client's
   error-class separation is contract surface).

**The verdict**: the v1.1 wire shape is implementable and testable as
designed; the both-ends fail-closure holds; the design's named paths
(the existence-hiding, the floor rejection) are fixture-provable with
modest effort. **The design's numbers hold.**

**The promotion**: the fixture corpus + the shim → WP14/WP1's seed (per
the spike-promotion rule). The spike's shim changes are committed on the
decision-engine branch as the spike artifact.

**The honestly-deferred paths**: the attestation-mismatch fixture (the
stamp⇄channel consistency check) requires the mTLS channel — the
v1-local posture is loopback trust (A1/T1: the auth seam is SaaS-phase);
the fixture lands with WP6's SaaS promotion. The partial-timeout fixture
exists in the seed (the fail-closed-timeout tightening) and passes.

## Spike (c) — The latency spike ✅ EVIDENCE-CITED (the re-measurement lands in WP4)

**The liveness (measured now)**: `up{job="sglang-clef-flash",
pod="sglang-clef-flash-5dbbc97f5b-jf8jb"} = 1` — the engine is live
(10.42.3.86:8001, llm_tier=decision, namespace=ai).

**The latency evidence**: the bake-off's measured provenance (2026-10-13,
recorded in the deployment manifest, measured on THIS corpus and card):
**p50 73–90 ms per decision**, agreement 91.8%/80.3%/80.0% (alert_class /
severity / needs_rca) on the 232-state held-out split. The design's
budget (1–5 s per decision point, inference-dominated) has ~10× headroom
at the measured p50.

**The verdict**: the latency budget holds on the measured evidence. The
independent re-measurement (a live solve through the v2 adapter) is
**WP4's DoD** — it requires the SystemOne request shape through the
adapter, which is the package's own integration test. The spike does not
duplicate it.

## Spike (b) — The facts-channel spike ⏳ DEFERRED-TO-WP9 (honest scope)

**The honest disposition**: the spike's subject — composing C1's seven
facts from the estate's real data — IS work package WP9 (the fact
composer). Hand-composing the facts in a spike script would test the
scripting, not the design; the composer's own tests are the spike's
proper form. **What the spike WILL measure when WP9 lands**: the
composition time against the budget (the seven facts' sources: the
attested conflict ledger, the windows, the incidents, the calendar), and
the sources' liveness. **What this spike contributes now**: the sources'
availability is confirmed (the estate's k8s state, the admin-api's ops
records, and the transition plan's conflict taxonomy are live and
queryable — verified during the transition plan's grounding). The block
report: nothing is blocked; the spike's proper form arrives with WP9.

## The go-package's empirical summary

The design's wire shape is implementable and fixture-provable (18/18);
the latency budget holds on the measured evidence (73–90 ms p50 vs the
1–5 s budget); the two spike findings are design CONFIRMATIONS (the
fail-conservative defaults and the error-class separation were the
design's stated principles — the seed's shortcuts violated them, and the
spike caught both). **The go decision's empirical questions are
answered.**
