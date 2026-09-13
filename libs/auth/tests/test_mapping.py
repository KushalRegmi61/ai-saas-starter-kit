"""Role ladder contract: ceiling per rung, cross-department, tenant stamped."""

import pytest
from pydantic import ValidationError

from auth.mapping import (
    DEFAULT_ROLE_POLICY,
    ROLE_LEVELS,
    UnknownRole,
    role_to_filter,
)
from auth.tokens import decode_assistant_token, mint_assistant_token
from auth.types import RoleDefinition, RolePolicy


def test_ladder_values():
    assert ROLE_LEVELS == {"employee": 1, "lead": 2, "manager": 3, "admin": 3}


def test_each_rung_maps_to_ceiling_with_tenant():
    assert role_to_filter("employee", tenant="assistant").max_access_level == 1
    assert role_to_filter("lead", tenant="assistant").max_access_level == 2
    assert role_to_filter("manager", tenant="assistant").max_access_level == 3
    assert role_to_filter("admin", tenant="assistant").max_access_level == 3


def test_no_department_scoping_for_now():
    spec = role_to_filter("manager", tenant="assistant")
    assert spec.departments == ["all"]
    assert spec.tenant == "assistant"


def test_unknown_role_raises():
    with pytest.raises(UnknownRole):
        role_to_filter("superuser", tenant="assistant")


def test_empty_tenant_rejected():
    with pytest.raises(ValueError):
        role_to_filter("manager", tenant="")


def test_service_policy_overrides_scope_and_ceiling():
    policy = RolePolicy(
        roles={
            "lead": RoleDefinition(
                max_access_level=2,
                departments=["security"],
                attributes={"project": "sentinel"},
            ),
            "admin": RoleDefinition(max_access_level=3),
        }
    )
    spec = role_to_filter("lead", tenant="svc", policy=policy)
    assert spec.departments == ["security"]
    assert spec.max_access_level == 2
    assert spec.attributes == {"project": "sentinel"}
    # Roles outside the service policy fail closed even if globally known.
    with pytest.raises(UnknownRole):
        role_to_filter("employee", tenant="svc", policy=policy)


def test_service_can_introduce_own_role_names():
    policy = RolePolicy(roles={"auditor": RoleDefinition(max_access_level=0)})
    spec = role_to_filter("auditor", tenant="svc", policy=policy)
    assert spec.max_access_level == 0
    token = mint_assistant_token(user_id="u-9", role="auditor", secret="s", roles=("auditor",))
    claims = decode_assistant_token(token, secret="s", roles=("auditor",))
    assert claims.role == "auditor"
    # The default vocabulary still rejects it.
    with pytest.raises(UnknownRole):
        role_to_filter("auditor", tenant="svc", policy=DEFAULT_ROLE_POLICY)


def test_policy_rejects_rung_above_default_scale():
    with pytest.raises(ValidationError):
        RolePolicy(roles={"x": RoleDefinition(max_access_level=9)})


def test_service_with_coarser_scale():
    policy = RolePolicy(
        roles={
            "viewer": RoleDefinition(max_access_level=0),
            "owner": RoleDefinition(max_access_level=1),
        },
        ceiling=1,
    )
    assert role_to_filter("owner", tenant="svc", policy=policy).max_access_level == 1


def test_service_with_finer_scale():
    policy = RolePolicy(
        roles={"superadmin": RoleDefinition(max_access_level=5)},
        ceiling=5,
    )
    spec = role_to_filter("superadmin", tenant="svc", policy=policy)
    assert spec.max_access_level == 5


def test_rung_above_service_ceiling_rejected():
    with pytest.raises(ValidationError):
        RolePolicy(
            roles={"owner": RoleDefinition(max_access_level=2)},
            ceiling=1,
        )
