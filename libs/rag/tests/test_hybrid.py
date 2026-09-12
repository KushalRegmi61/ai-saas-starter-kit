from rag.repo.neon_repo import SimpleDoc
from rag.retrieval.hybrid import reciprocal_rank_fusion


def test_rrf_prefers_doc_in_both_lists():
    a = SimpleDoc(text="pto policy", metadata={})
    b = SimpleDoc(text="other", metadata={})
    c = SimpleDoc(text="third", metadata={})
    merged = reciprocal_rank_fusion([(a, 0.9), (b, 0.8)], [(0, 5.0), (2, 1.0)], [a, b, c], top_k=3)
    assert merged[0][0].text == "pto policy"
