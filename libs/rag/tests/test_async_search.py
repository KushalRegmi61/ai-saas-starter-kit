"""Native async retrieval orchestration tests."""

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from rag.types import AccessFilter, SearchResponse, SearchResult, Source


@pytest.mark.asyncio
async def test_search_rag_async_runs_qdrant_sources_concurrently(monkeypatch):
    import rag.retrieval.search as search_mod

    settings = SimpleNamespace(
        reranker_top_n=20,
        embedding_dimensions=4,
        cache_ttl_hours=24,
    )
    monkeypatch.setattr(search_mod, "get_rag_settings", lambda: settings)

    async def embed(_question):
        return [0.1] * 4

    monkeypatch.setattr(search_mod.embeddings, "embed_query_async", embed)
    started = []

    async def semantic(*args):
        started.append("semantic")
        await asyncio.sleep(0)
        return [(SimpleNamespace(page_content="text", metadata={"source": "a.pdf"}), 0.9)]

    async def corpus(*args, **kwargs):
        started.append("corpus")
        await asyncio.sleep(0)
        return []

    monkeypatch.setattr(search_mod.qdrant_repo, "async_semantic_search", semantic)
    monkeypatch.setattr(search_mod.qdrant_repo, "async_scroll_corpus", corpus)
    monkeypatch.setattr(
        search_mod.reranker,
        "rerank",
        lambda question, candidates, top_k: candidates[:top_k],
    )

    class Connection:
        async def execute(self, *args, **kwargs):
            return None

        async def commit(self):
            return None

    @asynccontextmanager
    async def connection():
        yield Connection()

    monkeypatch.setattr(search_mod.neon_repo, "get_async_conn", connection)
    async def ensure_cache(*args, **kwargs):
        return None

    async def cache_get(*args, **kwargs):
        return None

    async def cache_put(*args, **kwargs):
        return None

    monkeypatch.setattr(search_mod.query_cache, "ensure_cache_table_async", ensure_cache)
    monkeypatch.setattr(search_mod.query_cache, "get_cached_answer_async", cache_get)
    monkeypatch.setattr(search_mod.query_cache, "store_cached_answer_async", cache_put)

    response = await search_mod.search_rag_async(
        "policy?",
        search_mode="semantic",
        access_filter=AccessFilter(departments=["all"], max_access_level=3),
    )

    assert isinstance(response, SearchResponse)
    assert response.results[0] == SearchResult(
        text="text", source=Source(source="a.pdf", score=0.9)
    )
    assert sorted(started) == ["corpus", "semantic"]
