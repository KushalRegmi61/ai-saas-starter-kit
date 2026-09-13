"""Deterministic query router, verbatim port of enterprise app/retrieval/query_router.py."""

from __future__ import annotations

import re
import unicodedata

_MAX_QUERY_CHARS = 1000
_MIN_ALPHA_RATIO = 0.30
_MIN_MEANINGFUL_WORDS = 1

_QUOTED_PHRASE = re.compile(r'"[^"]+"')
_POLICY_ID = re.compile(r"\b[A-Za-z]+-\d+\b")
_ALPHANUMERIC_CODE = re.compile(r"\b[A-Z][A-Z0-9]{2,}\b")
_VERSION_TAG = re.compile(r"\bv?\d+\.\d+\b")

_KEYWORD_RICH_MAX_WORDS = 6
_CONCEPTUAL_MIN_WORDS = 15

_SAFE_MODE = "hybrid"
_SAFE_REASON = "router:safe_fallback->hybrid"


def classify_query(question: str) -> tuple[str, str]:
    try:
        normalized, rejection_reason = _normalize(question)
        if rejection_reason:
            return _SAFE_MODE, f"router:rejected_input({rejection_reason})->hybrid"
        return _classify(normalized)
    except Exception as exc:
        return _SAFE_MODE, f"router:exception({type(exc).__name__})->hybrid"


def resolve_search_mode(question: str, search_mode: str) -> tuple[str, str]:
    if search_mode == "auto":
        return classify_query(question)
    return search_mode, f"caller_specified:{search_mode}"


def _normalize(raw: str) -> tuple[str, str]:
    if not isinstance(raw, str):
        return "", "not_a_string"
    text = raw[:_MAX_QUERY_CHARS]
    text = unicodedata.normalize("NFC", text)
    text = "".join(ch for ch in text if not unicodedata.category(ch).startswith("C") or ch in " \t")
    text = " ".join(text.split())
    if not text:
        return "", "empty_after_normalization"
    alpha_count = sum(1 for ch in text if ch.isalnum())
    if len(text) > 0 and alpha_count / len(text) < _MIN_ALPHA_RATIO:
        return "", f"low_alpha_ratio({alpha_count}/{len(text)})"
    words = [w for w in text.split() if any(ch.isalnum() for ch in w)]
    if len(words) < _MIN_MEANINGFUL_WORDS:
        return "", "no_meaningful_words"
    return text, ""


def _classify(text: str) -> tuple[str, str]:
    if _QUOTED_PHRASE.search(text):
        return "hybrid", "router:exact_phrase->hybrid"
    if _POLICY_ID.search(text):
        return "hybrid", "router:policy_id->hybrid"
    if _ALPHANUMERIC_CODE.search(text):
        return "hybrid", "router:acronym_or_code->hybrid"
    if _VERSION_TAG.search(text):
        return "hybrid", "router:version_tag->hybrid"
    word_count = len(text.split())
    if word_count <= _KEYWORD_RICH_MAX_WORDS:
        return "hybrid", f"router:short_query({word_count}w)->hybrid"
    if word_count >= _CONCEPTUAL_MIN_WORDS:
        return "semantic", f"router:long_conceptual({word_count}w)->semantic"
    return "hybrid", f"router:default({word_count}w)->hybrid"
