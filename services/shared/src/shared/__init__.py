"""Shared pure-Python primitives for backend services.

No third-party dependencies: everything here must stay importable by any
service (API, worker) without pulling service-specific SDKs.
"""

from shared.keys import has_path_traversal

__all__ = ["has_path_traversal"]
