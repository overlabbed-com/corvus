"""The decision core (WP3): the per-site solver dispatch, the per-site
timeout slicing, the partial success, the dependency composition.

The batch is the engine's unit; the decision point is the client's unit —
the core never conflates them (F3). The errors map carries every site that
did not answer, each with its registered conservative fail answer and the
verdict_class stamp (recognizably-not-an-answer, R-SEC-1a). The
answers∪errors invariant: every site lands in exactly one.

The timeout slicing: the budget is sliced per site (the budget is the
fail policy's TRIGGER — the error classes refine the record, F1's rule).
A site exceeding its slice does not starve the batch's other sites.

The dependency composition: a site declaring depends_on gets
dependency_failed(edge) when its dependency errored — the sentinel rule
makes the fail answers recognizably-not-answers, so the composition is
safe BY CONSTRUCTION (the dependent detects and abstains; the silent
substitution never happens).
"""
from __future__ import annotations

import time
from typing import Any, Callable


class SliceExceeded(Exception):
    pass


class AdapterUnavailable(Exception):
    pass


class DecisionCore:
    """The solver dispatch: (type, solver) → the answer_full."""

    def __init__(self, rules: dict[str, Callable] | None = None,
                 lookups: dict[str, Callable] | None = None,
                 adapter: Any = None):
        # The rule registry: site_id → the declared rule (the register's
        # criteria content, compiled). The lookup registry: site_id → the
        # lookup evaluation over the facts. The adapter: the model path (WP4).
        self.rules = rules or {}
        self.lookups = lookups or {}
        self.adapter = adapter

    # -- the public entry ---------------------------------------------------
    def solve(self, state: dict, facts: dict, sites: list[dict],
              budget_ms: int = 5000, request_ref: str | None = None) -> dict:
        slice_ms = budget_ms / max(1, len(sites))
        answers: dict[str, dict] = {}
        errors: dict[str, dict] = {}
        rows: list[dict] = []
        for entry in sites:
            sid = entry.get("site_id")
            # THE DEPENDENCY COMPOSITION: a declared dependency that errored
            # → dependency_failed(edge) — never the silent substitution.
            failed_dep = self._failed_dependency(entry, errors)
            if failed_dep:
                errors[sid] = self._fail_cell(
                    entry, code="dependency_failed",
                    reason_class=f"dependency_failed({failed_dep})",
                    extra={"failed_dependency_edge": failed_dep})
                continue
            deadline = time.monotonic() + slice_ms / 1000.0
            try:
                full = self._dispatch(entry, state, facts, deadline)
                answers[sid] = full
                rows.append({"site_id": sid, "answer_full": full,
                             "request_ref": request_ref})
            except SliceExceeded:
                errors[sid] = self._fail_cell(entry, code="timeout",
                                              reason_class="timeout")
            except AdapterUnavailable as exc:
                errors[sid] = self._fail_cell(entry, code="unavailable",
                                              reason_class=f"adapter:{exc}")
        return {"answers_full": answers, "errors": errors, "capture_rows": rows}

    # -- the dispatch -------------------------------------------------------
    def _dispatch(self, entry: dict, state: dict, facts: dict,
                  deadline: float) -> dict:
        sid = entry.get("site_id")
        solver = entry.get("solver")
        if solver == "rule":
            return self._dispatch_rule(entry, state, facts, deadline)
        if solver == "lookup":
            return self._dispatch_lookup(entry, state, facts, deadline)
        if solver == "model":
            return self._dispatch_model(entry, state, facts, deadline)
        raise AdapterUnavailable(f"solver {solver!r} has no dispatch")

    def _check_deadline(self, deadline: float):
        if time.monotonic() > deadline:
            raise SliceExceeded()

    def _dispatch_rule(self, entry: dict, state: dict, facts: dict,
                       deadline: float) -> dict:
        sid = entry.get("site_id")
        rule = self.rules.get(sid)
        if rule is None:
            # The honest default: the conservative floor (the last option in
            # the declared ordering) — marked rule-unregistered, never a
            # permissive guess.
            enum = list((entry.get("criteria") or {}).keys())
            return self._full(enum[-1] if enum else None,
                              reason="rule-unregistered")
        self._check_deadline(deadline)
        answer, probabilities = rule(state, facts, entry)
        # THE POST-HOC SLICE CHECK: the trigger is TIME — a rule that
        # overshoots its slice is a timeout even though it returned (the
        # budget trigger rule, F1; the cooperative-slice model).
        self._check_deadline(deadline)
        return self._full(answer, probabilities=probabilities)

    def _dispatch_lookup(self, entry: dict, state: dict, facts: dict,
                         deadline: float) -> dict:
        sid = entry.get("site_id")
        lookup = self.lookups.get(sid)
        if lookup is None:
            enum = list((entry.get("criteria") or {}).keys())
            return self._full(enum[-1] if enum else None,
                              reason="lookup-unregistered")
        self._check_deadline(deadline)
        answer, probabilities = lookup(state, facts, entry)
        self._check_deadline(deadline)
        return self._full(answer, probabilities=probabilities)

    def _dispatch_model(self, entry: dict, state: dict, facts: dict,
                        deadline: float) -> dict:
        if self.adapter is None:
            raise AdapterUnavailable("no adapter wired (WP4)")
        self._check_deadline(deadline)
        # The bounded internal retry (E6): one bounded re-ask.
        last: Exception | None = None
        for attempt in range(2):
            try:
                result = self.adapter.solve(entry, state, facts,
                                            deadline=deadline)
                return self._full(result["member"],
                                  probabilities=result.get("probabilities"))
            except SliceExceeded:
                raise
            except AdapterUnavailable:
                raise
            except Exception as exc:  # the bounded re-ask
                last = exc
        raise AdapterUnavailable(f"model path failed twice: {last}")

    # -- the helpers --------------------------------------------------------
    @staticmethod
    def _full(member, probabilities: dict | None = None,
              reason: str | None = None) -> dict:
        full = {"member": member,
                "probabilities": probabilities or {}}
        if reason:
            full["reason"] = reason
        return full

    def _fail_cell(self, entry: dict, code: str, reason_class: str,
                   extra: dict | None = None) -> dict:
        """The fail cell: the registered conservative answer + the verdict_class
        stamp — recognizably-NOT-an-answer (the sentinel rule, W4)."""
        fp = entry.get("fail_policy") or {}
        default = (fp.get("default") or {}).get("answer")
        cell = {"code": code, "reason_class": reason_class,
                "fail_answer": default,
                "verdict_class": f"fallback-verdict({code})"}
        if extra:
            cell.update(extra)
        return cell

    @staticmethod
    def _failed_dependency(entry: dict, errors: dict) -> str | None:
        for dep in entry.get("depends_on") or []:
            if dep in errors:
                return dep
        return None
