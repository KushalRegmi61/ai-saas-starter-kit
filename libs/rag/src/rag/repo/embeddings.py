"""Embedding adapter. Only file in retrieval/ that touches the OpenAI SDK (via repo)."""

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from rag.config import get_rag_settings


def _retry():
    s = get_rag_settings()
    return retry(
        retry=retry_if_exception_type((Exception,)),
        stop=stop_after_attempt(s.openai_retry_attempts),
        wait=wait_exponential(
            multiplier=1, min=s.openai_retry_min_wait, max=s.openai_retry_max_wait
        ),
        reraise=True,
    )


def _client():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise ImportError("openai is required for embeddings. Run: pip install openai") from exc
    s = get_rag_settings()
    if not s.openai_api_key:
        raise ValueError("OPENAI_API_KEY is missing. Set it before retrieval.")
    kwargs: dict = {"api_key": s.openai_api_key}
    if s.openai_base_url:
        kwargs["base_url"] = s.openai_base_url
    return OpenAI(**kwargs), s.embedding_model


@_retry()
def embed_texts(texts: list[str]) -> list[list[float]]:
    client, model = _client()
    resp = client.embeddings.create(model=model, input=texts)
    return [d.embedding for d in resp.data]


@_retry()
def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]
