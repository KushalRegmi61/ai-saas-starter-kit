from rag.retrieval.rbac import normalize_tenant, passes_access_filter
from rag.types import AccessFilter


def test_access_filter_carries_tenant_and_attributes():
    filt = AccessFilter(
        departments=["hr", "all", "general"],
        max_access_level=1,
        tenant="api",
        attributes={"project": "knowledge-assistant"},
    )
    assert filt.tenant == "api"
    assert filt.attributes == {"project": "knowledge-assistant"}


def test_access_filter_defaults_preserve_legacy_behavior():
    filt = AccessFilter(departments=["all"], max_access_level=0)
    assert filt.tenant is None
    assert filt.attributes == {}


def test_normalize_tenant():
    assert normalize_tenant(None) == "default"
    assert normalize_tenant("") == "default"
    assert normalize_tenant("api") == "api"


def test_passes_access_filter_enforces_tenant():
    meta = {"department": "hr", "access_level": "internal", "tenant": "api"}
    assert passes_access_filter(meta, ["hr"], 3, tenant="api") is True
    assert passes_access_filter(meta, ["hr"], 3, tenant="other") is False
    # Legacy points without a tenant key read as "default"
    legacy = {"department": "hr", "access_level": "internal"}
    assert passes_access_filter(legacy, ["hr"], 3, tenant="default") is True
    assert passes_access_filter(legacy, ["hr"], 3, tenant="api") is False
    # No tenant in filter disables the check (legacy behavior)
    assert passes_access_filter(meta, ["hr"], 3) is True


def test_qdrant_filter_includes_tenant():
    from rag.repo import qdrant_repo

    f = qdrant_repo._qdrant_filter(["hr"], 1, tenant="api")
    keys = [c.key for c in f.must]
    assert "tenant" in keys
    tenant_cond = next(c for c in f.must if c.key == "tenant")
    assert tenant_cond.match.value == "api"


def test_qdrant_filter_without_tenant_unchanged():
    from rag.repo import qdrant_repo

    f = qdrant_repo._qdrant_filter(["hr"], 1)
    assert [c.key for c in f.must] == ["department", "access_level"]
