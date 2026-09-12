"""Direct ingestion (Phase 2). Reserved: index_document() will live here.

No S3, no Lambda triggers — bytes arrive directly from the caller.
"""

from rag.ingestion.index import delete_indexed_source, index_document

__all__ = ["delete_indexed_source", "index_document"]
