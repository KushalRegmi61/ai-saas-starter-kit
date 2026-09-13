"""Role policy → retrieval policy. The lib ships a default ladder but the
consuming service owns its policy: pass a RolePolicy to define rungs,
ceilings, department scope, and extra attributes. Returns a plain FilterSpec
so this lib never imports libs/rag."""

from auth.types import FilterSpec, RoleDefinition, RolePolicy

# Retrieval ceilings only. 3 (restricted) is the top of the shared scale, so
# admin cannot outrank manager here — and that is intentional. Admin's
# authority is capability-based, not data-visibility-based: user CRUD,
# uploads, and bootstrap are gated on `claims.role == "admin"` by the
# consuming service (e.g. require_assistant_admin), never by FilterSpec.
ROLE_LEVELS: dict[str, int] = {
    "employee": 1,
    "lead": 2,
    "manager": 3,
    "admin": 3,
}

DEFAULT_ROLE_POLICY = RolePolicy(
    roles={name: RoleDefinition(max_access_level=level) for name, level in ROLE_LEVELS.items()}
)


class UnknownRole(RuntimeError):
    """Raised when mapping a role outside the service's policy."""


def role_to_filter(role: str, *, tenant: str, policy: RolePolicy | None = None) -> FilterSpec:
    if not tenant:
        raise ValueError("tenant must be a non-empty string")
    active = policy if policy is not None else DEFAULT_ROLE_POLICY
    if role not in active.roles:
        raise UnknownRole(f"unknown role: {role}")
    definition = active.roles[role]
    return FilterSpec(
        departments=list(definition.departments),
        max_access_level=definition.max_access_level,
        tenant=tenant,
        attributes=dict(definition.attributes),
    )
