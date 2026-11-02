"""Permission catalogue and role -> permission mapping.

Access control is deny-by-default: every protected endpoint requires an
explicit permission.  The frontend may hide controls the user lacks, but the
backend is the authority (see ``app.core.deps``).
"""
from __future__ import annotations

SUPER_ADMIN = "super_admin"
ADMIN = "admin"
RESEARCHER = "researcher"

ROLE_ORDER = [SUPER_ADMIN, ADMIN, RESEARCHER]

# permission key -> (human description, owning module)
PERMISSIONS: dict[str, tuple[str, str]] = {
    # --- Admin module -----------------------------------------------------
    "admin.users.read": ("View user accounts", "admin"),
    "admin.users.write": ("Create, update, activate/deactivate users and assign roles", "admin"),
    "admin.roles.read": ("View roles and their permissions", "admin"),
    "admin.data_sources.read": ("View data-source configurations", "admin"),
    "admin.data_sources.write": ("Create, update and remove data-source configurations", "admin"),
    "admin.data_sources.test": ("Run connection tests for data sources", "admin"),
    "admin.thresholds.read": ("View threshold configurations", "admin"),
    "admin.thresholds.write": ("Create, update and approve threshold configurations", "admin"),
    "admin.audit.read": ("View audit log entries", "admin"),
    # --- Research module --------------------------------------------------
    "research.datasets.read": ("Browse datasets and metadata", "research"),
    "research.ingest.run": ("Launch data-ingestion jobs", "research"),
    "research.processing.run": ("Launch preprocessing / indicator-computation jobs", "research"),
    "research.indicators.read": ("View indicator definitions and results", "research"),
    "research.compare.run": ("Compare time periods and datasets", "research"),
    "research.exports.create": ("Create export jobs", "research"),
    "research.exports.download": ("Download export outputs", "research"),
    # --- Disaster module ---------------------------------------------------
    "disaster.alerts.read": ("View disaster alerts and forecast records", "disaster"),
    "disaster.alerts.respond": ("Acknowledge, annotate and resolve alerts", "disaster"),
    "disaster.evaluate.run": ("Run threshold evaluations and record forecast values", "disaster"),
    # --- Report Generation module -------------------------------------------
    "reports.read": ("View generated reports and their summaries", "reports"),
    "reports.create": ("Build periodic and custom reports", "reports"),
    "reports.download": ("Download report files (PDF / CSV)", "reports"),
    # --- Public Data module ----------------------------------------------
    "public.publish": ("Decide what appears on the public dashboard (datasets, study areas, alerts)", "public"),
}

ROLE_PERMISSIONS: dict[str, set[str]] = {
    SUPER_ADMIN: {"*"},
    ADMIN: {
        "admin.users.read",
        "admin.users.write",
        "admin.roles.read",
        "admin.data_sources.read",
        "admin.data_sources.write",
        "admin.data_sources.test",
        "admin.thresholds.read",
        "admin.thresholds.write",
        "admin.audit.read",
        # administrators may inspect research outputs but do not need to run pipelines
        "research.datasets.read",
        "research.indicators.read",
        "research.exports.create",
        "research.exports.download",
        # disaster operations: evaluate, respond, monitor
        "disaster.alerts.read",
        "disaster.alerts.respond",
        "disaster.evaluate.run",
        # reports summarise data administrators can already read
        "reports.read",
        "reports.create",
        "reports.download",
        # publication decisions are an administrator responsibility
        "public.publish",
    },
    RESEARCHER: {
        "research.datasets.read",
        "research.ingest.run",
        "research.processing.run",
        "research.indicators.read",
        "research.compare.run",
        "research.exports.create",
        "research.exports.download",
        "disaster.alerts.read",
        "disaster.alerts.respond",
        "reports.read",
        "reports.create",
        "reports.download",
    },
}

ALL_PERMISSION_KEYS = set(PERMISSIONS)


def permissions_for_roles(role_names: set[str]) -> set[str]:
    """Union of permissions granted by the supplied roles."""
    perms: set[str] = set()
    for role in role_names:
        perms |= ROLE_PERMISSIONS.get(role, set())
    return perms


def role_grants(permission: str, role_names: set[str]) -> bool:
    perms = permissions_for_roles(role_names)
    return "*" in perms or permission in perms
