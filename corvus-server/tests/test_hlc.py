"""Unit tests for Hybrid Logical Clock (HLC) implementation.

TDD-driven development: These tests define the expected behavior.
"""

import json
import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from hlc import HLC, HLCTimestamp


class TestHLCBasicIncrement:
    """Test basic timestamp increment functionality."""

    def test_hlc_basic_increment(self):
        """Test that timestamps increment monotonically on same node."""
        hlc = HLC(node_id="node-1")

        ts1 = hlc.now()
        ts2 = hlc.now()
        ts3 = hlc.now()

        # Each subsequent timestamp should be greater
        assert ts2 > ts1
        assert ts3 > ts2
        assert ts1 < ts2 < ts3

        # Logical clock should increase when timestamps are close in time
        assert ts1.logical <= ts2.logical <= ts3.logical


class TestHLCUniqueness:
    """Test that timestamps are globally unique."""

    def test_hlc_uniqueness(self):
        """Generate 1000 timestamps and verify all are unique."""
        hlc = HLC(node_id="node-1")

        timestamps = [hlc.now() for _ in range(1000)]

        # All timestamps should be unique
        unique_timestamps = {str(ts) for ts in timestamps}
        assert len(unique_timestamps) == 1000

        # All should be comparable (total ordering)
        sorted_ts = sorted(timestamps)
        assert sorted_ts == timestamps


class TestHLCMergeCausalOrder:
    """Test merge operation for causal ordering."""

    def test_hlc_merge_causal_order(self):
        """Test that merge operation maintains causal ordering."""
        hlc1 = HLC(node_id="node-1")
        hlc2 = HLC(node_id="node-2")

        # Generate timestamps on different nodes
        ts1_a = hlc1.now()
        hlc2.now()

        # Simulate causal relationship: ts2_b happens after ts1_a
        # Node 2 receives ts1_a, then generates ts2_b
        merged = hlc2.merge(ts1_a)
        ts2_b = hlc2.now()

        # ts2_b should be after the merged timestamp
        assert ts2_b > merged

        # ts2_b should be after ts1_a (causal order preserved)
        assert ts2_b > ts1_a

    def test_hlc_merge_returns_greater(self):
        """Test that merge returns max of both timestamps."""
        hlc1 = HLC(node_id="node-1")
        hlc2 = HLC(node_id="node-2")

        ts1 = hlc1.now()
        ts2 = hlc2.now()

        # Merge should return a timestamp >= both inputs
        merged_from_1_to_2 = hlc2.merge(ts1)
        assert merged_from_1_to_2 >= ts1
        assert merged_from_1_to_2 >= ts2

        merged_from_2_to_1 = hlc1.merge(ts2)
        assert merged_from_2_to_1 >= ts1
        assert merged_from_2_to_1 >= ts2


class TestHLCSerialization:
    """Test JSON serialization/deserialization."""

    def test_hlc_serialization(self):
        """Test round-trip serialization to/from JSON."""
        hlc = HLC(node_id="test-node")
        ts = hlc.now()

        # Serialize to JSON
        json_str = ts.to_json()

        # Verify it's valid JSON
        parsed = json.loads(json_str)

        # Required fields should be present
        assert "physical" in parsed
        assert "logical" in parsed
        assert "node_id" in parsed
        assert isinstance(parsed["physical"], int)
        assert isinstance(parsed["logical"], int)
        assert isinstance(parsed["node_id"], str)

        # Deserialize back
        restored = HLCTimestamp.from_json(json_str)

        # Round-trip should preserve equality
        assert ts == restored
        assert ts.physical == restored.physical
        assert ts.logical == restored.logical
        assert ts.node_id == restored.node_id

    def test_hlc_deserialization(self):
        """Test deserialization from JSON dict."""
        data = {
            "physical": 1234567890,
            "logical": 42,
            "node_id": "test-node"
        }

        json_str = json.dumps(data)
        ts = HLCTimestamp.from_json(json_str)

        assert ts.physical == 1234567890
        assert ts.logical == 42
        assert ts.node_id == "test-node"

    def test_logical_increases_on_physical_backward(self, monkeypatch):
        """When physical clock moves backward, logical should increase."""

        hlc = HLC(node_id="node-1")
        hlc.now()

        # Mock time to return older timestamp

    def test_logical_increases_on_physical_backward(self, monkeypatch):
        """When physical clock moves backward, logical should increase."""
        import time

        hlc = HLC(node_id="node-1")

        # First call: use real time
        ts1 = hlc.now()
        last_physical = ts1.physical

        # Mock time to return older timestamp (older than last_physical)
        def mock_time_ns():
            return last_physical - 1000000  # 1ms older

        monkeypatch.setattr(time, "time_ns", mock_time_ns)
        ts2 = hlc.now()

        # Logical should have increased since physical went backward
        assert ts2.logical > ts1.logical, f"Expected logical {ts1.logical} < {ts2.logical}"

    def test_eq_with_non_hlctimestamp(self):
        """Equality with non-HLCTimestamp should return NotImplemented."""
        hlc = HLC(node_id="node-1")
        ts = hlc.now()

        assert ts == ts  # Self-equality
        assert ts != "string"  # Different type
        assert ts != 123  # Different type
        assert ts is not None  # None
