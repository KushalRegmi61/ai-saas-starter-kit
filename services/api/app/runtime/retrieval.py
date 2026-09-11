"""Retrieval routes: thin handlers over service/retrieval.py (no business logic)."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.repo.rag_auth import RagTokenClaims, claims_to_access_filter, require_rag_rate_limit
from app.service.retrieval import RetrievalUnavailable, search
from app.types.retrieval import SearchRequest, SearchResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/retrieval/search", response_model=SearchResponse)
def retrieval_search_endpoint(
    request: SearchRequest,
    claims: RagTokenClaims = Depends(require_rag_rate_limit),
) -> SearchResponse:
    try:
        return search(request, claims_to_access_filter(claims))
    except RetrievalUnavailable as e:
        raise HTTPException(status_code=503, detail=e.detail) from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from None
