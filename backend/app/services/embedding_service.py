"""
Embedding service - gọi Gemini API qua proxy OpenAI-compatible.

Theo PHASE2_SETUP.md (Migration Note): backend gọi thẳng ra proxy
https://api.shopaikey.com/v1 thay vì chạy model local.

Public API (giữ nguyên chữ ký như Phase 2 cũ):
- embed_passages(texts: list[str]) -> list[list[float]]
- embed_query(query: str) -> list[float]
- build_quiz_text(quiz) -> str
- build_question_text(question, quiz) -> str
"""

from __future__ import annotations

import logging
import time
from typing import Iterable, List, Optional, Sequence

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal HTTP helpers
# ---------------------------------------------------------------------------


def _truncate(text: str, max_chars: int) -> str:
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars].rsplit(" ", 1)[0] or text[:max_chars]


def _normalize(text: str) -> str:
    return " ".join((text or "").split())


def _require_api_key() -> str:
    if not settings.GEMINI_PROXY_API_KEY:
        raise RuntimeError(
            "GEMINI_PROXY_API_KEY chưa được cấu hình. "
            "Thêm vào backend/.env rồi restart backend."
        )
    return settings.GEMINI_PROXY_API_KEY


def _embeddings_url() -> str:
    base = settings.GEMINI_PROXY_BASE_URL.rstrip("/")
    return f"{base}/embeddings"


def _post_embeddings(
    inputs: Sequence[str],
    task_type: str,
    model: Optional[str] = None,
) -> List[List[float]]:
    """
    Gọi POST {base_url}/embeddings với retry + timeout.
    Trả về list vector theo thứ tự inputs.
    """
    api_key = _require_api_key()
    url = _embeddings_url()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or settings.EMBEDDING_MODEL,
        "input": list(inputs),
        "task_type": task_type,
        # gemini-embedding-001 mặc định trả 3072-dim; Qdrant collection cũng set 3072
        # nên KHÔNG ép output_dimensionality (proxy OpenAI-compatible có thể bỏ qua field này).
        # Nếu sau này muốn dim khác, set EMBEDDING_DIM=1536/768 và thêm lại dòng dưới.
    }

    last_err: Optional[Exception] = None
    attempts = settings.GEMINI_PROXY_MAX_RETRIES + 1
    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=settings.GEMINI_PROXY_TIMEOUT) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code >= 500 or resp.status_code == 429:
                    # server-side / rate-limit: retry
                    last_err = httpx.HTTPStatusError(
                        f"{resp.status_code} {resp.text[:200]}",
                        request=resp.request,
                        response=resp,
                    )
                    logger.warning(
                        "Gemini embeddings transient error (attempt %s/%s): %s",
                        attempt,
                        attempts,
                        last_err,
                    )
                    time.sleep(min(2 ** (attempt - 1), 5))
                    continue
                resp.raise_for_status()
                data = resp.json()

            items = data.get("data") or []
            vectors: List[List[float]] = []
            for item in items:
                vec = item.get("embedding")
                if not isinstance(vec, list):
                    raise RuntimeError(
                        f"Embedding response thiếu trường 'embedding': {item}"
                    )
                vectors.append([float(x) for x in vec])
            if len(vectors) != len(inputs):
                raise RuntimeError(
                    f"Embedding response sai số lượng: expect {len(inputs)}, got {len(vectors)}"
                )
            return vectors
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_err = e
            logger.warning(
                "Gemini embeddings transport error (attempt %s/%s): %s",
                attempt,
                attempts,
                e,
            )
            time.sleep(min(2 ** (attempt - 1), 5))
            continue

    raise RuntimeError(f"Gemini embeddings failed after {attempts} attempts: {last_err}")


def _batched(seq: Sequence[str], size: int) -> Iterable[List[str]]:
    if size <= 0:
        size = 1
    for i in range(0, len(seq), size):
        yield list(seq[i : i + size])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _prepare_inputs(texts: Sequence[str]) -> List[str]:
    cleaned: List[str] = []
    for t in texts:
        cleaned.append(_truncate(_normalize(t), settings.EMBEDDING_MAX_CHARS))
    return cleaned


def embed_passages(texts: Sequence[str]) -> List[List[float]]:
    """
    Embed documents/passages để lưu vào Qdrant.
    Trả về list[vector] theo đúng thứ tự input.
    """
    if not texts:
        return []
    inputs = _prepare_inputs(texts)
    results: List[List[float]] = []
    batch_size = max(1, settings.EMBEDDING_BATCH_SIZE)
    for batch in _batched(inputs, batch_size):
        vectors = _post_embeddings(batch, task_type="RETRIEVAL_DOCUMENT")
        results.extend(vectors)
    return results


def embed_query(query: str) -> List[float]:
    """
    Embed user query để search trong Qdrant.
    Dùng task_type=RETRIEVAL_QUERY để tối ưu cho truy vấn.
    """
    inputs = _prepare_inputs([query])
    if not inputs or not inputs[0]:
        raise ValueError("Query rỗng, không thể embed.")
    vectors = _post_embeddings(inputs, task_type="RETRIEVAL_QUERY")
    return vectors[0]


def embed_query_batch(queries: Sequence[str]) -> List[List[float]]:
    """Embed nhiều query cùng lúc (dùng cho cache / evaluation)."""
    if not queries:
        return []
    inputs = _prepare_inputs(queries)
    results: List[List[float]] = []
    batch_size = max(1, settings.EMBEDDING_BATCH_SIZE)
    for batch in _batched(inputs, batch_size):
        vectors = _post_embeddings(batch, task_type="RETRIEVAL_QUERY")
        results.extend(vectors)
    return results


# ---------------------------------------------------------------------------
# Text builders (giữ nguyên từ Phase 2)
# ---------------------------------------------------------------------------


def build_quiz_text(quiz) -> str:
    parts = [f"Quiz title: {quiz.title}"]
    if quiz.description:
        parts.append(f"Description: {quiz.description}")
    return "\n".join(parts)


def build_question_text(question, quiz) -> str:
    parts = [f"Quiz title: {quiz.title}"]
    if quiz.description:
        parts.append(f"Quiz description: {quiz.description}")
    parts.append(f"Question: {question.content}")
    return "\n".join(parts)
