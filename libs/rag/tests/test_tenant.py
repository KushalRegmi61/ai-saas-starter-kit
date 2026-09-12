from rag.retrieval.rbac import normalize_tenant
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
