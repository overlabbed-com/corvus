"""Hybrid Logical Clock — the event timestamp source (ADR-007's salvage).

Globally unique, causally ordered timestamps. Salvaged from the original
implementation (corvus-server/src/hlc.py, reviewed clean); thread-safety
fixed with a lock (the original carried a THREAD SAFETY WARNING — this
version is safe by construction).
"""
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class HLCTimestamp:
    physical: int  # wall-clock nanoseconds since epoch
    logical: int   # monotonic counter within the same physical tick
    node_id: str   # this deployment's identity (ADR-001: the fleet config)

    def __lt__(self, other: "HLCTimestamp") -> bool:
        if self.physical != other.physical:
            return self.physical < other.physical
        if self.logical != other.logical:
            return self.logical < other.logical
        return self.node_id < other.node_id

    def to_string(self) -> str:
        return f"{self.physical}:{self.logical}:{self.node_id}"


class HLC:
    def __init__(self, node_id: str):
        self._node_id = node_id
        self._physical = 0
        self._logical = 0
        self._lock = threading.Lock()

    def now(self) -> HLCTimestamp:
        with self._lock:
            physical = time.time_ns()
            if physical > self._physical:
                self._physical = physical
                self._logical = 0
            else:
                self._logical += 1
            return HLCTimestamp(self._physical, self._logical, self._node_id)

    def merge(self, remote: HLCTimestamp) -> HLCTimestamp:
        """Merge a remote timestamp (the receive event): the clock advances
        past both local and remote state — the causal-ordering guarantee."""
        with self._lock:
            physical = time.time_ns()
            if physical > self._physical and physical > remote.physical:
                self._physical, self._logical = physical, 0
            elif remote.physical > self._physical:
                self._physical, self._logical = remote.physical, remote.logical + 1
            elif self._physical > remote.physical:
                self._logical += 1
            else:
                self._physical = self._physical
                self._logical = max(self._logical, remote.logical) + 1
            return HLCTimestamp(self._physical, self._logical, self._node_id)
