"""Assistant identity boundary types. No logic, no imports from other layers."""

from pydantic import BaseModel, Field, model_validator

ASSISTANT_ROLES: tuple[str, ...] = ("employee", "lead", "manager", "admin")


class AssistantUser(BaseModel):
    """Public user shape. The password hash never leaves the store layer."""

    id: str
    email: str | None = None
    role: str = "employee"
    created_at: str | None = None


class AssistantClaims(BaseModel):
    """Verified token identity handed to service layers."""

    subject: str
    role: str
    issued_at: int
    expires_at: int


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class CreateUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=256)
    role: str = Field(pattern="^(employee|lead|manager|admin)$")


class RoleDefinition(BaseModel):
    """One rung of a service-defined role policy: access ceiling,
    department scope, and free-form attributes (e.g. future project scope).
    The lib validates the shape; the service decides the content. The
    ceiling is checked against the owning policy's scale (see RolePolicy)."""

    max_access_level: int = Field(ge=0)
    departments: list[str] = Field(default_factory=lambda: ["all"])
    attributes: dict[str, str] = Field(default_factory=dict)


class RolePolicy(BaseModel):
    """A complete role ladder owned by the consuming service. Passed whole —
    never merged with the default, so what the service defines is exactly
    what is enforced. `ceiling` is the highest level the service's
    enforcement backend understands (default 3 matches libs/rag's
    public→restricted scale); every rung must fit within it, so a policy
    can never grant what its backend cannot enforce."""

    roles: dict[str, RoleDefinition]
    ceiling: int = Field(default=3, ge=0)

    @model_validator(mode="after")
    def _rungs_fit_scale(self) -> "RolePolicy":
        for name, definition in self.roles.items():
            if definition.max_access_level > self.ceiling:
                raise ValueError(f"role {name!r} exceeds policy ceiling {self.ceiling}")
        return self


class FilterSpec(BaseModel):
    """Role-derived retrieval policy. The consuming service builds its own
    AccessFilter from this — libs/auth never imports libs/rag."""

    departments: list[str]
    max_access_level: int
    tenant: str
    attributes: dict[str, str] = Field(default_factory=dict)
