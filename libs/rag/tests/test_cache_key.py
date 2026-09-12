from rag.retrieval.query_cache import context_hash, make_cache_key


def test_context_hash_order_independent():
    assert context_hash(["b:1", "a:2"]) == context_hash(["a:2", "b:1"])


def test_cache_key_changes_with_context():
    assert make_cache_key("pto?", "c1") != make_cache_key("pto?", "c2")
