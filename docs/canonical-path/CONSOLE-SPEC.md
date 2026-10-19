# Corvus Console Spec — the operator's screen (the Tier 1 console's spine)

**Source**: the fleet-operator thread's chunk 3 + the review rulings + the
convergence contract, assembled per GAP-AUDIT.md's crystallization rule.

## The design thesis

The four channels (page, Slack, PR review, CI red) scatter by SOURCE. The
dashboard's one design move: reorder by **decision urgency** — what
expires, what's irreversible, who's watching. Source becomes metadata on
the payload, not the organizing principle. The operator stops triaging
channels and starts triaging decisions. The unit rendered everywhere is
the escalation payload — one canonical object, every channel a view of it.

## The five zones (one screen, each grounded in a real incident)

**ZONE 1 — THE INBOX** (decisions owed; the primary zone).
Renders unanswered payloads as cards: act-cases AND decline-cases in the
same inbox *[grounding: the decline that never reached a human]*.
Ordering: act-cases by expiry, then the reversibility class
(destructive/unknown above reversible), then audience visibility (the
live blog outranks internal surfaces at equal class); decline-cases by
cost-of-not-acting. The at-a-glance line the operator can hold: "3 owed ·
oldest expires 40min · all defaults conservative." Time-of-day rendering:
the same card pre-selects do-nothing-until-morning at 2am and the act
options at 9am — the risk-appetite context rendered, not assumed.

**ZONE 2 — THE CHANGE BOARD** (what the agents are doing right now).
Rows are changes, not PRs — each with the owner-agent, the target
surface, the pending-action class, and the COLLISION flags: composition
exposure (the merged state nobody rendered) *[the vhost displacement]*,
reconciliation effect ("this edit re-applies onto a completed Job"),
window collisions, lane validity ("this red is fleet-wide, not your
change"), dedup-superseded *[the bump flood that killed live pipelines]*.

**ZONE 3 — THE INCIDENT STRIP** (open incidents + who's on them).
Each row shows the stated cause AND whether raw evidence agrees — the
disagreement is RENDERED, never averaged away *[the wrong cause never
adjudicated]*. Owner state: which agent claimed response, which declined
(declines visible here too).

**ZONE 4 — THE TRUST LEDGER** (credibility, not a vanity score).
Per ACTION-CLASS, not per-agent: "image repins: 12/14 clean, 2
rollbacks." Rows are credibility events: narrative-vs-capture-trail
disagreements, verification-honesty misses, refusals surfaced vs silent,
operator class-table corrections *[the verify that passed but shouldn't
have — a credibility event nobody tallied]*.

**ZONE 5 — THE QUIET STRIP** (provably nothing failed silently —
fail-closed). The anti-incident-1 zone: dead-man signals that the decline
inbox is empty (provable emptiness, not assumed), the refusal store IS
being read, capture ingestion is live, alert delivery verified to a
human. If a check cannot run, the strip renders LOUD, not quiet. "No
news" must be evidence, not absence *[the store no human queries]*.

## The morning sequence (the actual 9am walk)

1. **Overnight defaults audit FIRST**: what did the conservative defaults
   EXECUTE while the operator slept — Zone 1 filtered to
   expired-with-default-executed.
2. **Zone 5**: prove nothing failed silently overnight.
3. **Zones 2–4**: what's in flight, what's broken, what's trending.

**The trust review is EXCEPTIONS-ONLY inside steps 1–2** (the review
ruling): the morning reviews what SPENT trust overnight (outcomes), not
what HOLDS trust (the map). Maps are pulled at decision time; mornings
audit what ran. Step 1 IS the trust review's primary moment (unattended
execution is where trust is spent — every overnight default execution
carries its outcome attestation; wrong-layer and missing attestations
surface here as trust exceptions). Step 2 gains the agent-side silence
check: the trust ledger's disqualifying-event counter must read
zero-since-last-review, provably and fail-closed. **The anti-wallpaper
rule**: anything reviewed on schedule with no action attached becomes
wallpaper — exceptions are action-attached by construction (each carries
a disposition: acknowledge / dispute / write a class-table row).

The four trust surfaces mapped onto the spine: the Trust Map = Zone 4
expanded, a PULL surface at decision time, never a morning push; the
Promotion Queue = Zone 4 extension, morning shows promoted-overnight
NOTIFICATIONS (read-only — under deterministic transitions the operator
must not be an approval gate) plus BLOCKED items only; the Audit Trail =
the record surface, entered FROM the exceptions; the Benchmark = console
surface, overnight reds arrive via the exception path.

## The in-place actions

Answer from the card: approve / approve-modified / do-nothing-until /
decline-or-override — the answer lands back in the capture record. The
confirm-or-correct tap for destructive/unknown classes; every correction
writes a class-table row. Supersede/pin (the M1 override point).
Red-attribution dismiss (mark the red environment-owned).

**THE NO-SILENT-DISMISSAL RULE**: there is no "ignore." Every item leaves
the screen only by being answered or expired-with-default-executed — both
recorded as decisions with their own capture rows. The dashboard must not
become a NEW unread store; the silent-decline failure mode is forbidden
here by construction.

## The anti-scatter contract

One payload, many views — the moment a channel formats its own copy, the
scatter returns. The console is where the full inbox lives; the page/Slack
surfaces render the SAME canonical object with no second payload format.

**The convergence contract** (the product strategist's Tier 1 console
inherits the spine): the payload as the render unit; the ordering keys
(expiry × class × audience; decline-cases by cost-of-not-acting); the
in-place action set + the no-silent-dismissal rule; the quiet-strip
fail-closed rule; decline-cases as first-class inbox rows. The strategist
ADDS beyond the spine: history/analytics views, the capture-record
browser, tier administration. **The boundary: the spine is the DECISION
surface; the console's other tabs are the RECORD surface.** Decisions
live on the spine; records are queryable behind it — never a decision
buried in a record browser.

## The data model

The console is a PROJECTION of the record store — no separate schema. The
inbox cards ← the record payloads; the trust ledger rows ← the credibility
events; the quiet strip ← the record-count reconciliation. "What you see
is what was decided" — no second source of truth to reconcile (the
audit-trail claim enterprises can put in front of an auditor). Tier 0 can
ship CLI-only because the console adds no new data.
