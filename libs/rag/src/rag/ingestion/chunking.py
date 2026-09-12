from langchain_text_splitters import RecursiveCharacterTextSplitter

from rag.config import get_rag_settings
from rag.repo.neon_repo import SimpleDoc


def chunk_documents(documents: list[SimpleDoc]) -> list[SimpleDoc]:
    settings = get_rag_settings()
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=["\n\n", "\n", ". ", " ", ""],
    )

    chunks: list[SimpleDoc] = []
    for document in documents:
        if document.metadata.get("content_type") == "table":
            # Tables must never be split mid-row — keep the entire markdown table
            # as one chunk regardless of size. A split table is unreadable and
            # produces wrong answers on row-based queries.
            chunks.append(
                SimpleDoc(
                    text=document.text,
                    metadata={**document.metadata, "chunk_index": 0},
                )
            )
        else:
            split_texts = splitter.split_text(document.text)
            for chunk_index, text in enumerate(split_texts):
                chunks.append(
                    SimpleDoc(
                        text=text,
                        metadata={**document.metadata, "chunk_index": chunk_index},
                    )
                )

    return chunks
