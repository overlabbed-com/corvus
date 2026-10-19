"""The fact composer (WP9): the provenance foundation's mechanism.

The facts are the provenance foundation of every probability claim the
register makes — a fact answers "what is true, including unknown"; the
composer assembles them from the sources AND stamps their provenance
(the three-clause rule's structural form).

The statuses (the design's ABSENT/UNKNOWN/STALE distinction, made
structural):
- **present** — the value + the as_of within the W7 freshness horizon.
- **unknown** — the source reports unknown: an honest answer about the
  world. The composer NEVER fabricates. The site's unknown-handling
  branch fires (the clause-1 discriminator).
- **stale** — a value EXISTS but the W7 horizon expired at consumption
  time: stamped distinctly (the audit can always distinguish "we didn't
  know" from "we knew something that expired"); the same handling branch
  as unknown.
- **ABSENT** — the source is not registered at all: the COMPOSER DEFECT.
  Reported to the caller → 400 missing_fact → fail-closed, fix the
  composer. Never silently skipped.

The provenance ladder: caller-stated < computed < engine-derived <
attested. The stamp travels: the capture row's facts_consumed ledger
records which fact CLASSES fed each answer (the W9 input ledger — the
poisoning detectable and scopeable post hoc).
"""
from __future__ import annotations

import time
from collections.abc import Callable

# The provenance ladder (the ordering from the architect's schema)
LADDER = ["caller-stated", "computed", "engine-derived", "attested"]

# The source result's shapes:
#   {"value": v, "provenance_class": cls, "as_of": ts}  → present (or stale)
#   {"unknown": reason}                                  → unknown
Source = Callable[[dict], dict]


class FactComposer:
    def __init__(self, sources: dict[str, Source],
                 freshness: dict[str, float] | None = None):
        # sources: the fact name → the source callable. The freshness: the
        # fact name → the W7 horizon in seconds (the absent = no horizon).
        self.sources = sources
        self.freshness = freshness or {}

    def compose(self, site: dict, now: float | None = None) -> tuple[dict, list[str]]:
        """Assemble the facts for a site's facts spec. Returns (facts,
        absent) — the absent = the composer defect (the caller 400s)."""
        now = now or time.time()
        facts: dict[str, dict] = {}
        absent: list[str] = []
        for fname, spec in (site.get("facts") or {}).items():
            source = self.sources.get(fname)
            if source is None:
                # ABSENT: the composer defect — reported, never skipped.
                absent.append(fname)
                continue
            result = source(spec) or {}
            if "unknown" in result:
                facts[fname] = {"name": fname, "value": None, "status": "unknown",
                                "reason": result["unknown"], "as_of": now,
                                "source": result.get("source", "unavailable"),
                                "provenance_class": result.get("provenance_class",
                                                              "unknown")}
                continue
            value = result.get("value")
            as_of = result.get("as_of", now)
            pclass = result.get("provenance_class", "caller-stated")
            status = "present"
            horizon = self.freshness.get(fname)
            if horizon is not None and (now - as_of) > horizon:
                status = "stale"  # the value kept; the stamp distinguishes
            facts[fname] = {"name": fname, "value": value, "status": status,
                            "as_of": as_of, "source": result.get("source", ""),
                            "provenance_class": pclass}
        return facts, absent

    def compose_status_view(self, facts: dict) -> dict:
        """The operator-legible view (the observe-mode fold): 'facts: N
        attested, 0 unknown, 1 stale' — the display renders from the
        stamps, never re-derives."""
        counts = {"attested": 0, "computed": 0, "engine-derived": 0,
                  "caller-stated": 0, "unknown": 0, "stale": 0}
        for f in facts.values():
            if f["status"] == "unknown":
                counts["unknown"] += 1
            elif f["status"] == "stale":
                counts["stale"] += 1
            else:
                counts[f.get("provenance_class", "caller-stated")] += 1
        return counts


# THE WORLD COMPOSER'S REFERENCE PROJECTION (M7/M5's pattern): the
# change_window — the bounded projection from the planned-activity
# calendar (the activities overlapping the decision's target + window,
# not the whole calendar). One calendar, two consumers (M7 and C1).
def change_window_source(calendar: list[dict], target: str | None = None):
    """Returns a source callable composing facts.change_window.
    calendar: [{activity, target?, window_start, window_end}]"""
    def source(spec) -> dict:
        now = time.time()
        relevant = [a for a in calendar
                    if (a.get("target") in (None, target))
                    and a["window_start"] <= now <= a["window_end"]]
        if relevant:
            end = min(a["window_end"] for a in relevant)
            return {"value": {"state": "active", "expires_at": end,
                              "as_of": now, "source": "planned-activity-calendar"},
                    "provenance_class": "computed", "as_of": now}
        upcoming = sorted([a for a in calendar
                           if a.get("target") in (None, target)
                           and a["window_start"] > now], key=lambda a: a["window_start"])
        next_activity = upcoming[0]["window_start"] if upcoming else None
        return {"value": {"state": "lapsed", "expires_at": None, "as_of": now,
                          "source": "planned-activity-calendar",
                          "next_activity": next_activity},
                "provenance_class": "computed", "as_of": now}
    return source
