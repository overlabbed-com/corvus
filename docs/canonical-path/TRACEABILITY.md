# Corvus Ideation Traceability — the load-bearing cross-expert routes

**Source**: this session's exchange history (the routed exchanges between
the five expert threads), reconstructed per the close-out goal's work
item 1. Granularity: the routes that CHANGED a design decision — the
assumption ledger (ASSUMPTION-LEDGER.md, 21 entries) is the floor for the
challenge→resolution level; this map adds the cross-expert routes at the
finding→route→change level. Routes not reconstructible from the session
record: none at this granularity — the session history carried every
routed exchange; courtesy acks are excluded by scope.

Format: FINDING (source expert, chunk) → TARGET (expert) → DESIGN CHANGE.

## From the security-governance thread

| Finding | Target | Design change |
|---|---|---|
| V1 state poisoning + the failure-mode-keyed policies (chunk 1) | architect | The register's fail-policy schema keys by failure mode; the failure-mode column enters the contract's error enum; the malformed→fail-closed rule |
| B3: "the capture store is the fleet-scoped state" invites the poison-serve seam (chunk 2) | architect | The store-class partition ADOPTED as the spec's vocabulary (five classes); the framing error conceded; the audit truth relocated to Corvus's decision records |
| R-SEC-1a + the observe-mode overlay (chunk 2.5) | product | The ramp's calendar replaced by the enforce-flip gate (canary re-run + reconciliation + governed change); the capture-admission controls live from day one |
| R-SEC-10 tamper-evidence + R-SEC-11 mode-aware evidence (chunk 2.5) | architect | The hash chain covers tombstones; the external anchor with the deadman; the governed WORM tombstone path; the observe-mode attempt records |
| The fail-policy audit matrix (chunk 3) | product | The matrix becomes the SLA table — the promise-shaped cells, the generated-view constraint, the quotable-cell rules |
| The fail-policy audit matrix (chunk 3) | architect | The shadow re-scoring confirmed (the canonical-form hash + the VOID-on-mismatch); P3 born (the plan-aggregate site); R-SEC-13's composition policy versioned |
| M3's refusal records (chunk 3) | operator | The refusal stream doubles as the quarantine sensor (folded into the operator's M3 spec) |
| The audit-trail must-record list (chunk 4) | architect | The facts-appendix as the FIFTH store class; the capacity isolation at three layers; the chain grammar over six record classes; the consume-call evidence-durability precondition |
| The audit-trail must-record list (chunk 4) | scientist | The facts snapshot as the re-decide substrate; the provenance classes catalog-defined; the noul quarantine rule |
| The audit-trail must-record list (chunk 4) | product | The record schema ships day-one in the wedge; the retention tiers bound Tier 0 storage |
| The trust-integrity skeleton (chunk 5) | product | Clauses 2/4/5 day-one for Tier 0; the trust surfaces' data source |
| The uncertainty-routing lens (addendum 3) | architect | The consumer contract structurally omits probabilities; the quantization at the response boundary (pre-trust-boundary); R-SEC-20's review dimensions |
| The trust-surfaces lens (addendum 5) | product | The narrative exclusion + the presentation discipline as promotion-UI requirements; the one-step decay + the shadow recursion |
| The pack supply chain (addendum 4, R-SEC-25..28) | product | The marketplace's observe-first pipeline confirmed with the gates slotted; the gap-duration SLA as promise material |

## From the decision-scientist thread

| Finding | Target | Design change |
|---|---|---|
| The register audit + W1–W11 (chunk 1) | architect | D1's boundary WIDENED (the catalog owns the enum content, the criteria content, the fail policy, the state schema with the provenance classes); "audit first, freeze second" |
| The register audit (chunk 1) | register | The three offenders repaired (E2's defer_review, P2's hazard screen, C2's declared bins + the sentinel); the meta-findings → the register v2's shape |
| The W1 boundary ruling (the three-clause rule) | architect | The fact composer = the provenance foundation's mechanism; ABSENT vs UNKNOWN made structural; the three-clause rule adopted as ENGINE-DESIGN's organizing principle |
| The W1 ruling (applied) | operator | The M1–M10 boundary call: four registerable, one split, one evidence lane; the governance-seed vs conduct-seed framing |
| The type/solver restructure (chunk 2) | architect | The catalog schema v2: two types × three solver classes; noul demoted to a solver restriction + the quarantine stamp; the score as derived (the bins as primary) |
| The uncertainty semantics (chunk 3) | architect | The weight_evaluation artifact family (the governance + calibration halves, the single admission record); the resolution field with the compile-time invariant; the facts-shape validation rejects probability payloads |
| The uncertainty semantics (chunk 3) | security | The calibration certificate = R-SEC-9's validity instrument (fail-closed at the gate); the non-propagation rule as a type-system fact; R-SEC-20 |
| The escalation design (chunk 4) | architect | The answered terminal state joins the delivery grammar (the seventh record class); the escalation_id join key |
| The escalation design (chunk 4) | register | The escalation registers as a site (solver: HUMAN); the three trigger classes; the six-component packet frozen at mint |
| The fail-policy science (chunk 5) | register | The direction taxonomy {open, pause, closed} replaces the family heuristic (2/6/5); the resolution-path field; the six-step derivation |
| The C1 decomposition (chunk 6) | register | The seven-part template; the option-space constraint law; the observe-mode fold (the sub-decisions ARE the display) |
| The trust-calibration semantics | product | The readiness meter renders the argmin verdict; the decay events as the cause-attributed feed; the granular freeze with named exits |
| The trust-calibration semantics | security | The certificate-staleness freeze formalized (per-site × per-weight-version); the decay events classified as quotable cells (four policy artifacts + the ratchet cell with the appeal site) |

## From the systems-architect thread

| Finding | Target | Design change |
|---|---|---|
| D1 hybrid catalog + D2 pure-function + D3 partial success (chunk 1) | all | The design baseline every later chunk refined |
| The store-class partition + the M-fixes' placement (chunk 3) | register | M5 → the world composer feeding facts.post_state; M3 → the outcome class on Corvus's decision record; M7 → the calendar as the fact source |
| The failure taxonomy F1–F10 (chunk 4) | contract | The quota_exhausted error; the one-retry-same-key rule; the three-state healthz (advisory); the budget-trigger rule |
| The deployment topology (chunk 5) | product | The three profiles as delivery bindings; the honest ledger justifying the seam (the failure-domain argument) |
| The provenance floor + the channel auth (the fold-ins) | security | R-SEC-19's prevention form; the mTLS cert-identity-as-principal; the stamp⇄channel consistency check (the attestation_mismatch code) |
| The monotonicity detector (the product routing) | register | The compiler's diff-classify stage; the change-class stamp; the downgrade-acknowledgment gate |
| The engine-derived fourth class (the sequential rule) | register | The provenance ladder gains engine-derived; the decision DAG acyclic by construction; supersession extends to decision-references |

## From the fleet-operator thread

| Finding | Target | Design change |
|---|---|---|
| M1–M10 (chunk 1) | register | Seven new-site candidates + three input fixes; the boundary ruling later classified them |
| The escalation payload (chunk 2) | scientist | The packet formalized (the six components); the payload's field-source contract (the capture spine vs the honesty surface vs the bridge) |
| The console (chunk 3) | product | The convergence contract: the spine inherited (the payload unit, the ordering keys, the no-silent-dismissal rule, the quiet strip); the anti-scatter constraint |
| The trust signals R4 (chunk 4) | security | The evidence spec for R-SEC-7: the layer rule, the promotion preconditions, the two hard rules (never promote on volume; the shadow form) |
| The conflict taxonomy R5 (chunk 4) | architect | C1's four-valued verdict + the seven-item required_facts + the re-check triggers; the seven→four collapse as the site's judgment |
| The review rulings | security | Clause 2 gains the row-due obligation, the WHO field, the due-set calibration denominator (the three-reconciliation family) |
| The review rulings | product | The morning sequence stays three steps; the trust review exceptions-only; the anti-wallpaper rule |

## From the product-strategist thread

| Finding | Target | Design change |
|---|---|---|
| The record-schema-day-one (chunk 4 route) | register | The wedge's minimum dependency set gains the full record schema; the flip gate = the three evidence-based criteria |
| The generated tier table (chunk 4 integration) | security | The promise grammar + the quotable-cell rules; the SLA table as a GENERATED VIEW of the register |
| The generated tier table (chunk 4 integration) | architect | The register→tier-table generator in the product build; the freshness gate; the sales-deck lint; the promise-monotonicity detector |
| The marketplace (chunk 2) | security | The pack supply-chain vectors (R-SEC-25..28): the poisoned pack, the outcome_binding gaming, the namespace escalation, the revocation path |
| The ratchet principle (chunk 2) | register | Promises only ratchet toward safety — at the register (downgrade events), the compiler (tightening-only overrides), the marketplace (certification gates enforcement) |
| Trust as a product (chunk 3) | scientist | The promotion-precondition calibration semantics (the readiness floor, the decay function, the certificate freeze) — the scientist's routed artifact |
| The boundaries (chunk 4) | product | The negative-space definition: eight nots, three edges, the growth rule |

## The routes the ledger does NOT capture (this map's additions)

The ledger records challenges to ASSUMPTIONS; this map records the
DESIGN-CHANGE routes — e.g., the security's matrix → the product's SLA
table (a product-surface change, not an assumption), the operator's
conflict taxonomy → the architect's C1 redesign (a contract-entry
change), the scientist's type/solver restructure → the catalog schema v2
(a schema change), the escalation answered-state → the chain grammar (a
grammar change). The two artifacts are complementary: the ledger for the
assumption level, this map for the design-change level.
