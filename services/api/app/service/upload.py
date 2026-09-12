import logging
import re

from shared.keys import has_path_traversal

from app.config import settings
from app.repo import (
    delete_file,
    get_file_metadata,
    get_object_bytes,
    get_object_head_bytes,
    get_presigned_upload_url,
    invalidate_list_cache,
)
from app.types import FileUploadResponse, PresignedUpload
from app.types.formatting import humanize_bytes

logger = logging.getLogger(__name__)

# image/svg+xml is excluded: embedded <script> would run as stored XSS.
# Re-add only with server-side SVG sanitization.
ALLOWED_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "application/pdf",
    "text/plain",
    "text/csv",
    "application/json",
    "application/zip",
    "video/mp4",
    "audio/mpeg",
    "audio/wav",
}

MIME_EXTENSION_MAP: dict[str, set[str]] = {
    "image/jpeg": {"jpg", "jpeg", "jfif"},
    "image/png": {"png"},
    "image/gif": {"gif"},
    "image/webp": {"webp"},
    "application/pdf": {"pdf"},
    "text/plain": {"txt", "text", "log", "md"},
    "text/csv": {"csv"},
    "application/json": {"json"},
    "application/zip": {"zip"},
    "video/mp4": {"mp4"},
    "audio/mpeg": {"mp3", "mpeg"},
    "audio/wav": {"wav"},
}


# Magic-byte signatures for binary types (declared content_type is untrusted).
# Text-like types have no reliable signature and skip this check.
def matches_content_signature(data: bytes, content_type: str) -> bool:
    """Leading bytes consistent with `content_type`; unknown types pass."""
    if content_type == "image/jpeg":
        return data[:3] == b"\xff\xd8\xff"
    if content_type == "image/png":
        return data[:8] == b"\x89PNG\r\n\x1a\n"
    if content_type == "image/gif":
        return data[:6] in (b"GIF87a", b"GIF89a")
    if content_type == "image/webp":
        return data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if content_type == "application/pdf":
        return data[:5] == b"%PDF-"
    if content_type == "application/zip":
        return data[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
    if content_type == "video/mp4":
        return data[4:8] == b"ftyp"  # ISO base media 'ftyp' box
    if content_type == "audio/mpeg":
        # ID3 tag, or an MPEG audio frame sync (11 set bits).
        return data[:3] == b"ID3" or (
            len(data) >= 2 and data[0] == 0xFF and (data[1] & 0xE0) == 0xE0
        )
    if content_type == "audio/wav":
        return data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    return True


_SAFE_FILENAME_RE = re.compile(r"[^\w\-.]")


def sanitize_filename(filename: str) -> str:
    """Sanitize filename: strip path components, remove unsafe chars, limit length."""
    name = filename.replace("\\", "/").split("/")[-1]
    name = name.replace("\x00", "")
    name = _SAFE_FILENAME_RE.sub("_", name)
    name = re.sub(r"[_.]{2,}", "_", name)
    name = name.lstrip(".").strip()
    if len(name) > 200:
        base, sep, ext = name.rpartition(".")
        # Keep a fitting extension, else hard-truncate. Guard on `sep` (not
        # `ext`): rpartition returns ("", "", name) with no dot.
        name = base[: 200 - len(ext) - 1] + "." + ext if sep and len(ext) < 200 else name[:200]
    return name or "unnamed"


def validate_extension_matches_type(filename: str, content_type: str) -> bool:
    """Verify the file extension is consistent with the declared MIME type."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed_exts = MIME_EXTENSION_MAP.get(content_type)
    if allowed_exts is None:
        return False
    if not ext:
        return True
    return ext in allowed_exts


class UploadError(Exception):
    """Raised when upload validation fails."""

    def __init__(self, detail: str, status_code: int = 400):
        self.detail = detail
        self.status_code = status_code
        super().__init__(detail)


# Declared RAG metadata allow-lists; unknown values are rejected (400).
VALID_DEPARTMENTS = {"hr", "security", "product", "finance", "general"}
VALID_ACCESS_LEVELS = {"public", "internal", "confidential", "restricted"}

# Types eligible for RAG auto-indexing; others finalize with rag_indexed=False.
RAG_INDEXABLE_TYPES: dict[str, set[str]] = {
    "application/pdf": {".pdf"},
    "text/plain": {".txt", ".md"},
}


def _maybe_index_in_rag(
    key: str,
    filename: str,
    content_type: str,
    department: str | None,
    access_level: str | None,
) -> bool:
    """Best-effort RAG auto-index of a finalized upload; never raises."""
    if content_type not in RAG_INDEXABLE_TYPES:
        return False
    if not (settings.qdrant_url and settings.rag_database_url):
        return False
    try:
        content = get_object_bytes(key)
        from rag import index_document

        index_document(
            content,
            filename,
            source=key,
            department=department,
            access_level=access_level,
            tenant=settings.rag_tenant,
        )
        return True
    except ValueError:
        return False
    except Exception:
        logger.exception("RAG auto-index failed: key=%s", key)
        return False


def upload_key_for(user_id: str, safe_name: str) -> str:
    """B2 key for a user's upload: ``uploads/{user_id}/{safe_name}``."""
    return f"uploads/{user_id}/{safe_name}"


def prepare_upload(
    filename: str,
    content_type: str,
    size_bytes: int,
    *,
    user_id: str,
) -> PresignedUpload:
    """Validate an upload intent and mint a scoped, type-bound presigned PUT.

    Bytes go browser→B2 directly (never through the API); size and signature
    are re-checked in :func:`finalize_upload`. Raises UploadError on failure.
    """
    if not filename:
        raise UploadError("No filename provided")

    if size_bytes <= 0:
        raise UploadError("Empty file")

    if size_bytes > settings.max_file_size:
        raise UploadError(
            f"File too large. Max size: {humanize_bytes(settings.max_file_size)}",
            status_code=413,
        )

    if content_type not in ALLOWED_TYPES:
        raise UploadError(f"File type '{content_type}' not allowed", status_code=415)

    safe_name = sanitize_filename(filename)

    if not validate_extension_matches_type(safe_name, content_type):
        raise UploadError(
            "File extension does not match declared content type",
            status_code=415,
        )

    key = upload_key_for(user_id, safe_name)
    upload_url = get_presigned_upload_url(key, content_type)
    return PresignedUpload(
        upload_url=upload_url,
        key=key,
        headers={"Content-Type": content_type},
    )


def _require_owned_upload(user_id: str, key: str) -> None:
    """Reject empty/traversing keys and keys outside the caller's prefix."""
    if not key or has_path_traversal(key):
        raise UploadError("Invalid file key")
    if not key.startswith(upload_key_for(user_id, "")):
        # 403 (not 404): this runs before any B2 call, so it leaks nothing
        # about other users' objects.
        raise UploadError("Invalid file key", status_code=403)


def finalize_upload(
    key: str,
    *,
    user_id: str,
    department: str | None = None,
    access_level: str | None = None,
) -> FileUploadResponse:
    """Confirm a direct upload landed and re-check size, type, and signature.

    Unconfirmed objects skip these checks (tracked tech-debt). Validates the
    declared RAG metadata, then best-effort auto-indexes. Raises UploadError.
    """
    _require_owned_upload(user_id, key)

    if department is not None and department not in VALID_DEPARTMENTS:
        raise UploadError(f"Unknown department '{department}'")
    if access_level is not None and access_level not in VALID_ACCESS_LEVELS:
        raise UploadError(f"Unknown access level '{access_level}'")

    metadata = get_file_metadata(key)
    if metadata is None:
        raise UploadError("Upload did not complete — object not found", status_code=404)

    if metadata.size_bytes == 0:
        delete_file(key)
        raise UploadError("Empty file")

    if metadata.size_bytes > settings.max_file_size:
        delete_file(key)
        raise UploadError(
            f"File too large. Max size: {humanize_bytes(settings.max_file_size)}",
            status_code=413,
        )

    if metadata.content_type not in ALLOWED_TYPES:
        delete_file(key)
        raise UploadError(f"File type '{metadata.content_type}' not allowed", status_code=415)

    header = get_object_head_bytes(key)
    if not matches_content_signature(header, metadata.content_type):
        # Stored bytes lied about their type — drop the object, then reject.
        delete_file(key)
        raise UploadError("File contents do not match the declared type", status_code=415)

    # Browser wrote straight to B2, bypassing the listing cache — invalidate it
    # so the new file shows up immediately instead of after the ~30s TTL.
    invalidate_list_cache()

    rag_indexed = _maybe_index_in_rag(
        metadata.key,
        metadata.filename,
        metadata.content_type,
        department,
        access_level,
    )

    return FileUploadResponse(
        key=metadata.key,
        filename=metadata.filename,
        size_bytes=metadata.size_bytes,
        size_human=metadata.size_human,
        content_type=metadata.content_type,
        uploaded_at=metadata.uploaded_at,
        url=metadata.url,
        rag_indexed=rag_indexed,
    )
