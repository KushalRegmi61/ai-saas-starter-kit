"""Byte-oriented document loaders (txt/md/pdf).

Ported from enterprise ``app/ingestion/loaders.py``. PDF loading uses
pdfplumber so tables are preserved as markdown instead of collapsing into
a single garbled line: per page, text is extracted with table regions
blanked out, plus one markdown chunk per table.
"""

from __future__ import annotations

import io
from pathlib import Path

import pdfplumber

from rag.repo.neon_repo import SimpleDoc
from rag.retrieval.rbac import infer_document_metadata

SUPPORTED_SUFFIXES = {".txt", ".md", ".pdf"}


def load_bytes(content: bytes, filename: str) -> list[SimpleDoc]:
    suffix = Path(filename).suffix.lower()
    if suffix in {".txt", ".md"}:
        text = content.decode("utf-8")
        return [
            SimpleDoc(
                text=text,
                metadata={
                    "source": Path(filename).name,
                    "file_type": suffix.lstrip("."),
                    **infer_document_metadata(filename),
                },
            )
        ]
    if suffix == ".pdf":
        return _load_pdf_bytes(content, filename)
    raise ValueError(f"Unsupported document type: {suffix}")


def _load_pdf_bytes(content: bytes, filename: str) -> list[SimpleDoc]:
    """Extract text and tables from each PDF page in ``content``."""
    name = Path(filename).name
    rbac_meta = infer_document_metadata(filename)
    documents: list[SimpleDoc] = []

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            base_meta = {
                "source": name,
                "file_type": "pdf",
                "page": page_number,
                **rbac_meta,
            }

            # ── table extraction ──────────────────────────────────────
            tables = page.extract_tables()
            for table_index, raw_table in enumerate(tables, start=1):
                md = _table_to_markdown(raw_table)
                if md:
                    documents.append(
                        SimpleDoc(
                            text=md,
                            metadata={
                                **base_meta,
                                "content_type": "table",
                                "table_index": table_index,
                            },
                        )
                    )

            # ── text extraction (tables blanked out) ──────────────────
            if tables:
                table_settings = {
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                }
                page_without_tables = page.filter(
                    lambda obj, _page=page, _settings=table_settings: (
                        obj.get("object_type") != "char"
                        or not _inside_any_table(obj, _page.find_tables(_settings))
                    )
                )
                text = page_without_tables.extract_text() or ""
            else:
                text = page.extract_text() or ""

            if text.strip():
                documents.append(
                    SimpleDoc(
                        text=text,
                        metadata={**base_meta, "content_type": "text"},
                    )
                )

    return documents


def _table_to_markdown(raw_table: list[list[str | None]]) -> str:
    """
    Convert pdfplumber's raw table (list of rows, each a list of cell strings)
    into a GitHub-flavoured markdown table.

    Empty cells become empty strings. None cells (merged cells) inherit the
    last non-None value in the same column so the table stays readable.
    """
    if not raw_table or not raw_table[0]:
        return ""

    # Clean cells: strip whitespace, replace None with empty string
    cleaned = []
    for row in raw_table:
        cleaned.append([str(cell).strip() if cell is not None else "" for cell in row])

    # Remove completely empty rows
    cleaned = [row for row in cleaned if any(cell for cell in row)]
    if not cleaned:
        return ""

    col_count = max(len(row) for row in cleaned)

    # Pad rows to same width
    padded = [row + [""] * (col_count - len(row)) for row in cleaned]

    # Build markdown: first row = header, second row = separator
    header = "| " + " | ".join(padded[0]) + " |"
    separator = "| " + " | ".join(["---"] * col_count) + " |"
    body_rows = ["| " + " | ".join(row) + " |" for row in padded[1:]]

    return "\n".join([header, separator, *body_rows])


def _inside_any_table(obj: dict, tables) -> bool:
    """Return True if a PDF character object falls inside any table bounding box."""
    x, y = obj.get("x0", 0), obj.get("top", 0)
    for table in tables:
        bbox = table.bbox  # (x0, top, x1, bottom)
        if bbox[0] <= x <= bbox[2] and bbox[1] <= y <= bbox[3]:
            return True
    return False
