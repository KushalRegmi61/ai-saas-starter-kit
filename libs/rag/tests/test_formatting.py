from rag.retrieval.formatting import answer_sources, format_context, source_from_metadata
from rag.types import SearchResult


def test_format_context_block_shape():
    r = SearchResult(
        text="hello", source=source_from_metadata({"source": "hr_policy.pdf", "page": 2}, 0.9)
    )
    assert format_context([r]) == "[1] Source: hr_policy.pdf, page 2\nhello"


def test_answer_sources_prefers_citation():
    results = [
        SearchResult(text="a", source=source_from_metadata({"source": "hr_policy.pdf"}, 0.9)),
        SearchResult(text="b", source=source_from_metadata({"source": "other.pdf"}, 0.9)),
    ]
    assert answer_sources("see hr_policy.pdf for details", results)[0]["source"] == "hr_policy.pdf"
