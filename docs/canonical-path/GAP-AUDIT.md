# The Gap-Pattern Audit — the ideation's output surface

**The finding that started this audit** (the ideation's completion review):
the threat model — real, rigorous analytical work — exists only as process
residue. The security thread's vector-driven method named every attack and
mapped each to an R-SEC requirement and a placed mechanism, but no single
durable artifact captures the model as a unit. The work exists; the
artifact does not; and because the work exists, nothing looks missing.

## 1. The pattern, formalized

**Definition**: a PROCESS-RESIDUE GAP is work-product whose substance
exists only as process residue — conversation chunks, derivation prose,
coordination-log entries, requirement justifications embedded in other
documents — with no single durable, reviewable artifact capturing it as a
unit.

**Structure** (three preconditions, all necessary):
1. **The work was done as a process, not a deliverable** — the analysis
   happened live (an expert thread, a review loop, a derivation) and its
   output was consumed immediately by the next step rather than crystallized.
2. **The substance is distributed** — it survives only in fragments spread
   across multiple surfaces (chunks, justifications, summaries), so no
   single fragment looks incomplete.
3. **The consuming artifacts summarize rather than carry** — downstream
   documents reference the work ("per the fail-policy audit", "R-SEC-9
   requires…") without reproducing it, which creates the *appearance* of
   coverage.

**Why it stays invisible**: every check that asks "was this done?" answers
yes — the work WAS done, and its conclusions are embedded in the design.
Only a check that asks "where does this live?" — a durability test, not a
completeness test — finds it. The gap is invisible to completeness review
because completeness is about the design, and the design is fine.

**The falsifiable survival test**: *if this conversation were lost, would
the substance survive in the repo?* Applied per work-product: trace the
substance's claims to a committed artifact; if the chain terminates in
conversation-only content, the surface fails.

**The negative control (the test discriminates)**: applied to
ASSUMPTION-LEDGER.md and ENGINE-DESIGN.md — both PASS. The ledger's twenty
entries are self-contained (assumption, source, challenge, resolution);
the architecture spec carries its claims directly. If the conversation
were lost, both survive intact. The test therefore discriminates: it
passes where the artifact exists and fails where only residue does (the
threat model fails it — the vector catalog, the per-site exploitation
notes, and the attacker posture do not survive as a unit anywhere in the
repo).

## 2. The audit method

For each surface: (1) name the work-product the thread delivered; (2)
apply the survival test — trace its substance into the committed
artifacts; (3) disposition: CONSOLIDATE (material, recoverable from
existing content — crystallize now), ALREADY-COVERED (the artifact
carries it), DEFER-WITH-REASON (a build-phase artifact; the design intent
is captured), LOST-RECORDED (the substance is conversation-only and the
consolidations captured it incompletely — record the loss honestly).

The evidence base: the 16 artifacts in docs/canonical-path/ (read from
disk) + the chunk content in this session's history (the process residue
itself — which is why this audit is executable at all, and why it is also
the recovery mechanism).

## 3. The surface checklist

| # | Surface | Work-product | Method | Result |
|---|---|---|---|---|
| a1 | Security: threat model | the vector catalog (V1, V2a, V2b, V3, V5, false-unknown, stored-injection, laundering, supply-chain, identity, fatigue, timing), the attacker posture, the per-site exploitation notes | survival test: trace the vectors into the artifacts | **FAIL → CONSOLIDATE** (THREAT-MODEL.md) |
| a2 | Security: R-SEC catalog | R-SEC-1..30 with amendments (1a, 2-divergence, 7×3, 9×3, 13-nonpropagation) | trace each requirement to one place | **FAIL → CONSOLIDATE** (R-SEC-CATALOG.md) |
| a3 | Security: failure-mode matrix | the full site × failure-code × mode table | compare TRUST-SPEC's promise statements vs the chunk's table | **PASS (mostly)** — the promise statements cover every site (uniform + per-code); the per-site *exploitation* notes are threat-model material → folded into a1 |
| b1 | Scientist: W-criteria audit verdicts | the 13 seed sites' audit (offenders + the passes with conditions) | DECISION-REGISTER-V2.md carries 3 offenders + the repairs; the remaining 9 verdicts are chunk-only | **FAIL → CONSOLIDATE** (the register-audit section) |
| b2 | Scientist: per-site fail-policy derivations | the six-step procedure's applications | the chunk delivered the aggregate (2/6/5) + C1's derivation; per-site reasoning beyond C1 was never delivered even as residue | **LOST-RECORDED → RECONSTRUCTED** (post-audit: FAIL-POLICY-DERIVATIONS.md — the procedure applied to the recorded per-site data, under-determined fields marked for the sweep) |
| b3 | Scientist: probe evidence | the five live probes' findings | the findings are embedded in the design decisions (the type system, the quarantine); DECISION-REGISTER-V2 cites them | **PASS** |
| c1 | Architect: fold-in deltas | the provenance schema, the channel auth, the join grammar, the dual-copy witness, the chain grammar | ENGINE-DESIGN.md carries the store-class table, the witness web, the chain grammar; the detailed schemas (the source-credential stamp fields, the decision_ref fields) are chunk-only | **PARTIAL → CONSOLIDATE-lite** (the schema details fold into R-SEC-CATALOG.md's mechanism notes) |
| c2 | Architect: the honest ledger | the six gains vs six costs | ENGINE-DESIGN.md §5 carries it | **PASS** |
| d1 | Product: pack anatomy + tier-table generator | the six-section pack YAML, the generator's mechanics (the freshness gate, the sales-deck lint, the monotonicity detector) | PRODUCT.md carries the design intent; the artifact schemas are P4 build-phase deliverables | **DEFER-WITH-REASON** (P4; freezing the pack format now would pre-empt the build) |
| d2 | Product: pricing two-axis model | the usage × quotable-cell-coverage axes, the three-state rendering | PRODUCT.md carries it | **PASS** |
| e1 | Operator: escalation payload | the seven sections (A–G) + the field-source contract | DECISION-REGISTER-V2 names "the seven sections"; the content is chunk-only | **FAIL → CONSOLIDATE** (ESCALATION-SPEC.md) |
| e2 | Operator: console spec | the five zones, the morning sequence, the in-place actions, the anti-scatter contract | BUILD-PLAN P2 names them; the content is chunk-only | **FAIL → CONSOLIDATE** (CONSOLE-SPEC.md) |
| e3 | Operator: conflict taxonomy | the seven conflict classes with estate grounding | DECISION-REGISTER-V2's C1 section has the four-valued verdict; the seven-class input taxonomy is chunk-only | **FAIL → CONSOLIDATE** (into the register doc's C1 section) |
| f1 | Coordination: route-level traceability | finding → route → design change | the assumption ledger captures the challenge→resolution level; the route-level web is conversation-only | **LOST-RECORDED → RECONSTRUCTED** (post-audit: TRACEABILITY.md — the load-bearing routes from the session's exchange history) |
| f2 | Coordination: chunk-text durability | the ~35 chunks' full text | the log holds 6 files; the consolidations captured the substance (verified per-surface above); the verbatim texts are conversation-only | **LOST-RECORDED → NOT-RECONSTRUCTIBLE-WITH-REASON** (post-audit: the verbatim texts are conversation-only and pasting them would be lossy archive, not consolidation; the substance is carried by the per-surface-verified consolidations) |
| g1 | Review + ledger completeness | the adversarial review's dispositions, the 20 ledger entries | both are committed, self-contained artifacts | **PASS — the negative control** |

## 4. The instance table (dispositions)

| Instance | Disposition | Evidence |
|---|---|---|
| The threat model | CONSOLIDATE → THREAT-MODEL.md | the vectors, the posture, the exploitation notes trace only to chunks |
| The R-SEC catalog | CONSOLIDATE → R-SEC-CATALOG.md | 30 requirements in 11 documents' justifications, no single list |
| The W-criteria audit verdicts (9 unconsolidated sites) | CONSOLIDATE → the register-audit section | chunk-1's audit is the only record for I1, I2, B1, E1, P1, T1, T2, W1, C1-detail |
| The escalation payload spec | CONSOLIDATE → ESCALATION-SPEC.md | R2's sections A–G + the field-source contract are chunk-only |
| The console spec | CONSOLIDATE → CONSOLE-SPEC.md | R3's zones + morning sequence + actions are chunk-only |
| The conflict taxonomy | CONSOLIDATE → the register doc's C1 section | the seven classes with estate grounding are chunk-only |
| The architect's detailed schemas | CONSOLIDATE-lite → R-SEC-CATALOG.md's mechanism notes | the stamp and decision_ref field lists are chunk-only |
| The failure-mode matrix | ALREADY-COVERED | TRUST-SPEC's promise statements carry every cell |
| The probe evidence | ALREADY-COVERED | the findings are embedded; the register cites the probes |
| The honest ledger, the pricing model | ALREADY-COVERED | ENGINE-DESIGN §5, PRODUCT.md |
| The pack anatomy + the tier-table generator | DEFER-WITH-REASON | P4 build-phase artifacts; the intent is captured |
| The per-site fail-policy derivations | LOST-RECORDED → RECONSTRUCTED | FAIL-POLICY-DERIVATIONS.md; under-determined fields marked for the sweep |
| The route-level traceability | LOST-RECORDED → RECONSTRUCTED | TRACEABILITY.md; the load-bearing routes |
| The chunk-text durability | LOST-RECORDED → NOT-RECONSTRUCTIBLE-WITH-REASON | the verbatim texts; the substance is carried |

**Counts**: CONSOLIDATE 7 · ALREADY-COVERED 4 · DEFER-WITH-REASON 1 ·
LOST-RECORDED 3.

## 4b. The post-audit closures (the close-out goal's work item 6)

The three LOST-RECORDED instances were revisited with the operator's
confirmed depth (assess all three; reconstruct the honest two):

- **The route-level traceability → RECONSTRUCTED** as TRACEABILITY.md:
  the load-bearing finding→route→design-change map from the session's
  exchange history — the design-change level the assumption ledger does
  not capture.
- **The per-site fail-policy derivations → RECONSTRUCTED** as
  FAIL-POLICY-DERIVATIONS.md: the six-step procedure applied to the
  RECORDED per-site data (the direction taxonomy, the exploitation
  notes, the register repairs), every field provenance-marked
  ([R] recorded / [D] derived-at-consolidation / [S] under-determined,
  marked for the register sweep). Zero invented conclusions; the
  aggregate check reproduces the recorded 2/6/5 exactly.
- **The chunk-text durability → NOT-RECONSTRUCTIBLE-WITH-REASON**: the
  verbatim texts are conversation-only; reproducing them would be lossy
  archive, not consolidation. The substance is carried by the
  per-surface-verified consolidations — the honest terminal disposition.

Also closed post-audit: the seed artifacts (DECISION-REGISTER.md,
ENGINE-CONTRACT.md, decision-register.yaml) were found UNTRACKED on the
branch — the audit's own pattern in miniature — and committed
(housekeeping). The durability correction is ingested to the knowledge
base for future-session retrieval.

## 5. The pattern's meta-lesson

The gap stayed invisible through an entire ideation phase whose explicit
purpose was "challenge every design assumption" — because the assumption
ledger challenges DESIGN assumptions, and this gap is not a design
assumption. It is a **durability** property of the work-product itself.
The correction is procedural, not analytical: every ideation work-product
earns an artifact at the moment its consuming step completes, or it is
recorded as residue with a disposition. The survival test ("if this
conversation were lost…") is the check that makes the pattern findable.
