"""Backward-compatible aggregate for API and domain models."""

from __future__ import annotations

from .api_models import (
    EnrollmentAttestationRequest,
    EnrollmentMode,
    EnrollmentRegisterRequest,
    EnrollmentTokenRequest,
    LifecycleActionRequest,
)
from .domain_models import (
    AdoptionReport,
    Blueprint,
    DashboardSummary,
    FleetSummary,
    NodeIdentity,
    NodeRecord,
    NodeStatus,
    NodeSummary,
    Organization,
    Tenant,
    TenantTier,
)

__all__ = [
    "AdoptionReport",
    "Blueprint",
    "DashboardSummary",
    "EnrollmentAttestationRequest",
    "EnrollmentMode",
    "EnrollmentRegisterRequest",
    "EnrollmentTokenRequest",
    "FleetSummary",
    "LifecycleActionRequest",
    "NodeIdentity",
    "NodeRecord",
    "NodeStatus",
    "NodeSummary",
    "Organization",
    "Tenant",
    "TenantTier",
]
