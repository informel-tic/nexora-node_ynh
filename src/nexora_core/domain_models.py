"""Shared domain and persisted-state models used across Nexora layers."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


NodeStatus = Literal[
    "discovered",
    "bootstrap_pending",
    "agent_installed",
    "attested",
    "registered",
    "healthy",
    "degraded",
    "draining",
    "revoked",
    "retired",
]

EnrollmentMode = Literal["push", "pull"]


class Organization(BaseModel):
    """Business entity owning one or more fleets."""

    org_id: str
    name: str
    owner_email: str
    created_at: str


class TenantTier(str, Enum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class Tenant(BaseModel):
    """Isolated environment within an organization."""

    tenant_id: str
    org_id: str
    name: str
    tier: TenantTier = "free"
    max_nodes: int = 5
    max_apps: int = 10
    created_at: str


class NodeSummary(BaseModel):
    """High-level status and inventory counters for a managed node."""

    node_id: str
    hostname: str
    status: NodeStatus = "discovered"
    enrollment_mode: Optional[EnrollmentMode] = None
    yunohost_version: Optional[str] = None
    ynh_version: Optional[str] = None
    debian_version: Optional[str] = None
    agent_version: Optional[str] = None
    last_seen: Optional[str] = None
    last_inventory_at: Optional[str] = None
    enrolled_by: Optional[str] = None
    token_id: Optional[str] = None
    apps_count: int = 0
    domains_count: int = 0
    certs_ok: int = 0
    backups_count: int = 0
    health_score: int = 0
    pra_score: int = 0
    security_score: int = 0
    notes: List[str] = Field(default_factory=list)
    allowed_transitions: List[str] = Field(default_factory=list)
    profile: Optional[str] = None
    roles: List[str] = Field(default_factory=list)
    cordoned: bool = False
    capabilities: Dict[str, Any] = Field(default_factory=dict)
    tenant_id: Optional[str] = None
    organization_id: Optional[str] = None


class NodeIdentity(BaseModel):
    """Persistent node identity and credential metadata."""

    node_id: str
    fleet_id: str
    tenant_id: Optional[str] = None
    organization_id: Optional[str] = None
    token_id: str
    credential_type: str = "token+key"
    certificate_subject: str
    key_path: str
    cert_path: str
    expires_at: str
    rotation_recommended_at: str
    revoked_at: Optional[str] = None


class NodeRecord(NodeSummary):
    """Persisted node record stored in state.json."""

    registered_at: Optional[str] = None
    status_updated_at: Optional[str] = None
    credential_expires_at: Optional[str] = None
    credential_revoked_at: Optional[str] = None
    compatibility: Dict[str, Any] = Field(default_factory=dict)


class Blueprint(BaseModel):
    slug: str
    name: str
    description: str
    activity: str
    profiles: List[str] = Field(default_factory=list)
    recommended_apps: List[str] = Field(default_factory=list)
    subdomains: List[str] = Field(default_factory=list)
    security_baseline: Dict[str, Any] = Field(default_factory=dict)
    monitoring_baseline: List[str] = Field(default_factory=list)
    pra_baseline: List[str] = Field(default_factory=list)
    portal: Dict[str, Any] = Field(default_factory=dict)


class DashboardSummary(BaseModel):
    node: NodeSummary
    top_apps: List[Dict[str, Any]] = Field(default_factory=list)
    alerts: List[str] = Field(default_factory=list)
    services: List[Dict[str, Any]] = Field(default_factory=list)
    certs: List[Dict[str, Any]] = Field(default_factory=list)
    backups: List[Dict[str, Any]] = Field(default_factory=list)
    raw: Dict[str, Any] = Field(default_factory=dict)


class FleetSummary(BaseModel):
    nodes: List[NodeSummary]
    total_nodes: int
    total_apps: int
    total_domains: int
    overall_health_score: int


class AdoptionReport(BaseModel):
    recommended_mode: str
    existing_apps_count: int = 0
    existing_domains_count: int = 0
    collisions: List[Dict[str, Any]] = Field(default_factory=list)
    safe_to_install: bool = True
    notes: List[str] = Field(default_factory=list)


__all__ = [
    "AdoptionReport",
    "Blueprint",
    "DashboardSummary",
    "EnrollmentMode",
    "FleetSummary",
    "NodeIdentity",
    "NodeRecord",
    "NodeStatus",
    "NodeSummary",
    "Organization",
    "Tenant",
    "TenantTier",
]