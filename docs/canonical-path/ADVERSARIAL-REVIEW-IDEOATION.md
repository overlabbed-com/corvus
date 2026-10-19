# The Ideation's Adversarial Review — findings and dispositions

**The review**: the estate's adversarial-review machinery (the wiggum loop,
3 rounds, 6 operational perspectives) run against the consolidated design
(the four artifacts) before the build plan closes. "The ideation that
reviews the harness must itself be reviewed."

**The verdict**: 13 findings (5 high, 6 medium, 2 low). Every HIGH is
dispositioned below — three are design refinements folded into the
artifacts, two are build-phase decisions the build plan carries.

## The HIGH findings, dispositioned

### 1. Ambiguous trust boundary for the fact composer / attested stores
**Disposition: ALREADY ADDRESSED — the review input omitted the mechanism.**
The design specifies the trust boundary in full: mTLS on the Corvus↔engine
channel with the cert identity as the fleet principal (the security
capstone's call, the architect's fold-in), every fact carries a
source-credential stamp `{component, credential, attested_at}`, the
boundary validates stamp⇄channel consistency (a stamp claiming a credential
the channel didn't present → 400 `attestation_mismatch`), and the two
attribution planes are stated (mTLS for components, OIDC for humans).
The reviewer's emphasis on cryptographic verification over metadata checks
is CONFIRMED as the design's existing shape — the stamp's trust comes FROM
the channel authentication, which the architect named as the interlock.
**Residual for the build plan**: the fact-composer's key material management
(per-component certs, rotation) lands in the auth-seam spec.

### 2. Opaque provenance-floor failures lack actionable remediation paths
**Disposition: DESIGN REFINEMENT — folded into the contract spec.**
The 400 `provenance_below_floor` rejection's error payload gains the
structured fields: `failed_fact_id`, `required_provenance_class`,
`observed_provenance_class`. The contract v1.1 error envelope's field list
is amended. A validate-only endpoint (dry-run provenance compliance) is a
build-phase feature candidate — noted in the build plan's P1 backlog.

### 3. Verdict-token issuer SPOF + replay attack surface
**Disposition: BUILD-PHASE DECISIONS — carried in the build plan.**
The design has the token's properties (single-use, TTL-bound, action-bound,
evidence-durability precondition) and the atomic consumption validation,
but the HA/DR strategy and the storage mechanism for the single-use
enforcement are build-phase decisions: the consumption ledger's storage
(the estate's SQLite WAL pattern vs a distributed nonce store), the
issuer's replication strategy, the break-glass procedure for prolonged
issuer outages. The build plan's P1 carries these as named decisions.

### 4. Verdict-token issuer HA/DR strategy
**Disposition: BUILD-PHASE DECISIONS — same as #3.** The RTO/RPO and the
HA configuration are P1 deliverables. Note: the fail-closed posture during
issuer unavailability IS the designed behavior (the fleet's autonomy floor
drops to the registered fail-policy floor) — the HA question is about
restoring capacity, not about safety.

### 5. Opaque provenance-floor failures (duplicate of #2)
**Disposition: merged with #2.**

## The MEDIUM findings (deployment-phase concerns)

Network policy isolation for the fact composer and the stores · the
persistent storage strategy for the capture store and the evidence lane ·
the DNS resolution path · the mTLS enforcement mechanism at the network
layer · the resource profiles and scaling for the decision core · the PDBs
and rollout strategy. **Disposition: these are deployment-manifest concerns,
not design gaps — the build plan's deployment section carries them as a
checklist** (the homelab's own netpol-audit discipline applies).

## The LOW findings

Pod security standards for the decision-engine namespace · structured JSON
logging for the decision components. **Disposition: noted in the build
plan's hardening checklist** (the structured logging fields: request_hash,
site_id, solver_type, provenance_check_result, decision_outcome, token_id,
latency_ms).

## The review's net effect

No finding contradicts the design's core commitments. The review confirms
the trust boundary's importance, demands the error payloads' structure
(folded), and names the token-issuer HA as the build phase's named
decision (carried). **The ideation's own adversarial review is complete:
the consolidated design survives it with refinements, no refutations.**
