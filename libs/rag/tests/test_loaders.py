import pytest

from rag.ingestion.loaders import load_bytes


def test_load_txt_and_md():
    docs = load_bytes(b"# hello\n\nworld", "notes.md")
    assert len(docs) == 1 and docs[0].text.startswith("# hello")
    assert docs[0].metadata["source"] == "notes.md"


def test_unsupported_suffix_raises():
    with pytest.raises(ValueError):
        load_bytes(b"GIF89a...", "cat.gif")
