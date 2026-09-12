from rag.ingestion.chunking import chunk_documents
from rag.repo.neon_repo import SimpleDoc


def test_tables_never_split():
    big_table = "| a |\n| --- |\n" + "| row |\n" * 500
    out = chunk_documents([SimpleDoc(text=big_table, metadata={"content_type": "table"})])
    assert len(out) == 1 and out[0].metadata["chunk_index"] == 0


def test_text_splits_with_overlap():
    out = chunk_documents([SimpleDoc(text="word " * 500, metadata={})])
    assert len(out) > 1 and all("chunk_index" in d.metadata for d in out)
