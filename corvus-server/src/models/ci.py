"""Configuration Item (CI) models."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

# Valid CI types — matches spec/cmdb.md taxonomy
CI_TYPES = frozenset({
    "search", "index", "app", "model", "flow", "endpoint",
    "automation", "integration", "library", "queue",
    "account", "credential", "license", "subscription",
    "cert", "zone", "record", "vlan", "firewall_rule",
    "dataset", "snapshot", "backup_job",
    "disk", "nic", "psu", "controller", "device", "scene", "bridge", "sensor"
})

# Valid operational statuses
CI_STATUSES = frozenset({"active", "expiring", "expired", "revoked", "decommissioned"})

# Valid relationship types
CI_RELATIONSHIPS = frozenset({
    "BELONGS_TO", "CONTAINS", "INSTALLED_ON", "DEPENDS_ON", "USES",
    "READS_FROM", "WRITES_TO", "AUTHENTICATES_WITH", "FEEDS",
    "LOADED_ON", "STORED_ON", "HOSTED_ON", "SECURES", "PROXIED_BY",
    "ROUTES_TO", "MANAGED_BY", "AFFECTS_CI", "CHANGED_BY",
    "MONITORED_BY", "EXPIRES_TO", "RENEWS_TO"
})


class CIRequest(BaseModel):
    """Request to register a Configuration Item."""
    name: str = Field(..., description="Unique CI identifier")
    ci_type: str = Field(..., description=f"CI type: {', '.join(sorted(CI_TYPES))}")
    service_name: str | None = Field(None, description="Associated service name")
    expires_at: str | None = Field(None, description="Expiry timestamp (ISO8601 UTC)")
    parent_ci: str | None = Field(None, description="Parent CI (for hierarchies)")
    operational_status: str = Field("active", description=f"Status: {', '.join(sorted(CI_STATUSES))}")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Additional CI metadata")

    def model_post_init(self, __context: Any) -> None:
        """Validate CI type and status."""
        if self.ci_type not in CI_TYPES:
            raise ValueError(f"Invalid ci_type: {self.ci_type}. Must be one of: {', '.join(sorted(CI_TYPES))}")
        if self.operational_status not in CI_STATUSES:
            valid = ', '.join(sorted(CI_STATUSES))
            raise ValueError(f"Invalid operational_status: {self.operational_status}. Must be one of: {valid}")


class CIResponse(BaseModel):
    """Response for CI details."""
    name: str
    ci_type: str
    service_name: str | None
    expires_at: str | None
    parent_ci: str | None
    operational_status: str
    metadata: dict[str, Any]
    days_until_expiry: int | None = None
    created_at: str
    updated_at: str
    relationships: dict[str, list[str]] = Field(default_factory=dict)

    @classmethod
    def from_row(cls, row, relationships: dict[str, list[str]] | None = None):
        """Create from database row."""
        import json

        days_until_expiry = None
        if row["expires_at"]:
            try:
                expiry = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
                days_until_expiry = (expiry - datetime.now(UTC)).days
            except (ValueError, TypeError):
                pass

        # Parse metadata from JSON string if needed
        metadata = row["metadata"]
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        elif not metadata:
            metadata = {}

        return cls(
            name=row["name"],
            ci_type=row["ci_type"],
            service_name=row["service_name"],
            expires_at=row["expires_at"],
            parent_ci=row["parent_ci"],
            operational_status=row["operational_status"],
            metadata=metadata,
            days_until_expiry=days_until_expiry,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            relationships=relationships or {},
        )


class CIImpactResponse(BaseModel):
    """Response for CI impact analysis."""
    ci_name: str
    ci_type: str
    direct_dependents: list[str] = Field(default_factory=list)
    indirect_dependents: list[str] = Field(default_factory=list)
    services_using: list[str] = Field(default_factory=list)
    change_window_required: bool = True
    risk_level: str = "medium"  # low, medium, high, critical


class CIExpiryResponse(BaseModel):
    """Single CI in expiry list."""
    name: str
    ci_type: str
    expires_at: str
    days_left: int
    service_name: str | None
    operational_status: str


class CIExpiryQueryResponse(BaseModel):
    """Response for expiry queries."""
    expiring_in_7_days: list[CIExpiryResponse] = Field(default_factory=list)
    expiring_in_30_days: list[CIExpiryResponse] = Field(default_factory=list)
    expiring_in_90_days: list[CIExpiryResponse] = Field(default_factory=list)
    already_expired: list[CIExpiryResponse] = Field(default_factory=list)
