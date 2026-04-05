"""Hybrid Logical Clock (HLC) implementation for Corvus Mesh Core.

Provides globally unique, causally ordered timestamps for federated systems.

The HLC combines:
- Physical timestamp (wall clock time in nanoseconds)
- Logical clock (monotonically increasing counter within same physical second)

This ensures:
- Global uniqueness: timestamps are unique across all nodes
- Causal ordering: if event A happens-before B, then HLC(A) < HLC(B)
- Real-time ordering: timestamps correlate with wall-clock time

THREAD SAFETY WARNING:
This implementation is NOT thread-safe. The now() and merge() methods perform
read-modify-write operations on internal state (_logical, _last_physical) without
locks. For concurrent access from multiple threads, wrap calls in a threading.Lock:

    with hlc_lock:
        ts = hlc.now()
        hlc.merge(remote_ts)
"""

from dataclasses import dataclass
import time
import json
from typing import Optional


@dataclass(frozen=True)
class HLCTimestamp:
    """Hybrid Logical Clock timestamp.

    Attributes:
        physical: Wall-clock time in nanoseconds since epoch
        logical: Monotonically increasing counter within same physical second
        node_id: Unique identifier for the node that generated this timestamp
    """
    physical: int
    logical: int
    node_id: str

    def __post_init__(self) -> None:
        """Validate timestamp components after creation."""
        if self.physical < 0:
            raise ValueError("Physical timestamp must be non-negative")
        if self.logical < 0:
            raise ValueError("Logical clock must be non-negative")
        if not self.node_id:
            raise ValueError("Node ID must be non-empty")

    def __lt__(self, other: "HLCTimestamp") -> bool:
        """Less-than comparison for ordering."""
        if self.physical != other.physical:
            return self.physical < other.physical
        if self.logical != other.logical:
            return self.logical < other.logical
        # If physical and logical are equal, use node_id as tie-breaker
        return self.node_id < other.node_id

    def __le__(self, other: "HLCTimestamp") -> bool:
        """Less-than-or-equal comparison."""
        return self == other or self < other

    def __gt__(self, other: "HLCTimestamp") -> bool:
        """Greater-than comparison."""
        return other < self

    def __ge__(self, other: "HLCTimestamp") -> bool:
        """Greater-than-or-equal comparison."""
        return other <= self

    def __eq__(self, other: object) -> bool:
        """Equality comparison."""
        if not isinstance(other, HLCTimestamp):
            return NotImplemented
        return (self.physical, self.logical, self.node_id) == \
               (other.physical, other.logical, other.node_id)

    def __hash__(self) -> int:
        """Hash for use in sets and dicts."""
        return hash((self.physical, self.logical, self.node_id))

    def to_json(self) -> str:
        """Serialize to JSON string."""
        data = {
            "physical": self.physical,
            "logical": self.logical,
            "node_id": self.node_id
        }
        return json.dumps(data)

    @classmethod
    def from_json(cls, json_str: str) -> "HLCTimestamp":
        """Deserialize from JSON string."""
        data = json.loads(json_str)
        return cls(
            physical=data["physical"],
            logical=data["logical"],
            node_id=data["node_id"]
        )


class HLC:
    """Hybrid Logical Clock generator.

    Provides causally ordered, globally unique timestamps across distributed nodes.

    Usage:
        hlc = HLC(node_id="my-node")
        ts = hlc.now()

        # Merge with remote timestamp (when receiving events from other nodes)
        remote_ts = HLCTimestamp(physical=123, logical=45, node_id="remote")
        local_hlc.merge(remote_ts)
    """

    def __init__(self, node_id: str) -> None:
        """Initialize HLC with unique node identifier.

        Args:
            node_id: Unique string identifier for this node (must be unique cluster-wide)
        """
        if not node_id:
            raise ValueError("Node ID must be non-empty")
        self._node_id = node_id
        self._logical = 0
        self._last_physical = 0

    @property
    def node_id(self) -> str:
        """Return the node ID."""
        return self._node_id

    def now(self) -> HLCTimestamp:
        """Generate a new HLC timestamp.

        Returns:
            HLCTimestamp with incremented logical clock if within same physical second,
            or new physical timestamp with logical reset to 0.
        """
        current_physical = time.time_ns()

        if current_physical <= self._last_physical:
            # Clock moved backwards or stayed same - increment logical clock
            self._logical += 1
            self._last_physical = current_physical
        else:
            # Clock moved forward - reset logical clock
            self._logical = 0
            self._last_physical = current_physical

        return HLCTimestamp(
            physical=self._last_physical,
            logical=self._logical,
            node_id=self._node_id
        )
    def merge(self, remote_ts: HLCTimestamp) -> HLCTimestamp:
        """Merge remote timestamp into local state.

        Updates local state to encode causal awareness of the remote timestamp.
        The returned timestamp has this node's node_id (not remote_ts.node_id).

        Args:
            remote_ts: Timestamp from a remote node

        Returns:
            New HLCTimestamp with this node_id that encodes causal knowledge
            of remote_ts. The timestamp is guaranteed to be >= both the local
            state and remote_ts.
        """
        current_physical = time.time_ns()

        # Take maximum of physical times
        max_physical = max(current_physical, remote_ts.physical)

        # Update logical clock to be at least max(local, remote)
        self._logical = max(self._logical, remote_ts.logical)

        # Advance last_physical if we saw a newer time
        if max_physical > self._last_physical:
            self._last_physical = max_physical
            # Physical clock moved forward, reset logical
            self._logical = 0

        return HLCTimestamp(
            physical=self._last_physical,
            logical=self._logical,
            node_id=self._node_id
        )
