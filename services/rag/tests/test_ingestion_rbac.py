from rag.retrieval.rbac import infer_document_metadata


def test_infer_prefix_and_fallback():
    assert infer_document_metadata("hr_policy.pdf") == {
        "department": "hr",
        "access_level": "confidential",
    }
    assert infer_document_metadata("random.txt") == {
        "department": "general",
        "access_level": "internal",
    }
