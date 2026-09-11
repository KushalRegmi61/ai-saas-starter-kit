from rag.retrieval.query_router import classify_query


def test_policy_id_routes_hybrid():
    mode, _ = classify_query("What does HR-001 say about leave?")
    assert mode == "hybrid"


def test_long_conceptual_routes_semantic():
    q = "Can you explain in detail how the entire leave approval workflow operates across teams and managers today?"
    mode, _ = classify_query(q)
    assert mode == "semantic"


def test_garbage_never_throws():
    mode, _ = classify_query("?????")
    assert mode == "hybrid"
