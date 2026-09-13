from rag.retrieval.rbac import passes_access_filter


def test_all_department_sees_general_public():
    assert (
        passes_access_filter({"department": "general", "access_level": "public"}, ["all"], 0)
        is True
    )


def test_level_ceiling_enforced():
    meta = {"department": "hr", "access_level": "confidential"}
    assert passes_access_filter(meta, ["hr", "all"], 1) is False
    assert passes_access_filter(meta, ["hr", "all"], 2) is True


def test_department_isolation():
    assert (
        passes_access_filter({"department": "finance", "access_level": "public"}, ["hr"], 3)
        is False
    )
