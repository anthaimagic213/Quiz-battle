"""
LLM service - gọi Gemini API qua proxy OpenAI-compatible.

Theo PHASE3_GEMINI_MIGRATION.md mục 6.2:
- POST {GEMINI_PROXY_BASE_URL}/chat/completions
- Mặc định model: gemini-2.5-flash
- Hỗ trợ system + user/assistant history
- Trả về {answer, usage, raw}
- Có safe_chat_completion() với fallback message
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings
from app.services.llm_error_handler import (
    call_with_resilience,
    get_circuit_breaker,
    CircuitBreakerOpen,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class LLMError(RuntimeError):
    """Lỗi chung khi gọi LLM (response sai format, thiếu config, ...)."""
    pass


class LLMConnectionError(LLMError):
    """
    Raised khi KHÔNG kết nối được tới LLM proxy (timeout, transport error,
    5xx, 429 sau khi đã retry hết).

    Tách riêng khỏi LLMError để orchestrator có thể short-circuit: khi proxy
    chết thì cả router, embedding (semantic search) và composer đều sẽ chết,
    nên ta trả về 1 thông báo "AI tạm thời không khả dụng" thay vì để lỗi
    cascade qua nhiều bước.
    """
    pass


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------


def _require_api_key() -> str:
    if not settings.GEMINI_PROXY_API_KEY:
        raise LLMError(
            "GEMINI_PROXY_API_KEY chưa được cấu hình. "
            "Thêm vào backend/.env rồi restart backend."
        )
    return settings.GEMINI_PROXY_API_KEY


def _chat_completions_url() -> str:
    base = settings.GEMINI_PROXY_BASE_URL.rstrip("/")
    return f"{base}/chat/completions"


def _post_chat_completion(
    messages: List[Dict[str, Any]],
    temperature: float,
    max_tokens: int,
    model: str,
    response_format: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
) -> Dict[str, Any]:
    api_key = _require_api_key()
    url = _chat_completions_url()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        payload["response_format"] = response_format
    if tools:
        payload["tools"] = tools
        if tool_choice is not None:
            payload["tool_choice"] = tool_choice

    last_err: Optional[Exception] = None
    transport_failed = False
    attempts = settings.GEMINI_PROXY_MAX_RETRIES + 1
    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=settings.GEMINI_PROXY_TIMEOUT) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code >= 500 or resp.status_code == 429:
                    transport_failed = True
                    last_err = httpx.HTTPStatusError(
                        f"{resp.status_code} {resp.text[:200]}",
                        request=resp.request,
                        response=resp,
                    )
                    logger.warning(
                        "Gemini chat transient error (attempt %s/%s): %s",
                        attempt,
                        attempts,
                        last_err,
                    )
                    time.sleep(min(2 ** (attempt - 1), 5))
                    continue
                resp.raise_for_status()
                data = resp.json()
            return data
        except (httpx.TimeoutException, httpx.TransportError) as e:
            transport_failed = True
            last_err = e
            logger.warning(
                "Gemini chat transport error (attempt %s/%s): %s",
                attempt,
                attempts,
                e,
            )
            time.sleep(min(2 ** (attempt - 1), 5))
            continue

    # Hết retry mà vẫn fail do mất kết nối / proxy chết -> báo riêng để
    # orchestrator short-circuit thay vì để lỗi cascade.
    if transport_failed:
        raise LLMConnectionError(
            f"Không kết nối được tới LLM proxy sau {attempts} lần thử: {last_err}"
        )
    raise LLMError(f"Gemini chat failed after {attempts} attempts: {last_err}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def chat_completion(
    messages: List[Dict[str, Any]],
    temperature: float = 0.4,
    max_tokens: int = 800,
    model: Optional[str] = None,
    response_format: Optional[Dict[str, Any]] = None,
    tools: Optional[List[Dict[str, Any]]] = None,
    tool_choice: Optional[Any] = None,
    use_circuit_breaker: bool = True,
) -> Dict[str, Any]:
    """
    Gọi Gemini proxy /chat/completions với circuit breaker protection.

    Args:
        messages: list[{"role": "system"|"user"|"assistant", "content": "..."}]
        temperature: 0.0 - 1.0
        max_tokens: giới hạn token output
        model: override model (mặc định settings.LLM_MODEL)
        response_format: vd {"type": "json_object"} để force JSON output
        tools: list function schema (OpenAI-compatible function calling)
        tool_choice: "auto" | "none" | {"type": "function", "function": {...}}
        use_circuit_breaker: True = bật circuit breaker (default)

    Returns:
        {
            "answer": str,
            "tool_calls": list[dict] | None,  # [{id, name, arguments(dict)}]
            "usage": {"prompt_tokens": int, "completion_tokens": int},
            "raw": dict  # raw response
        }

    Raises:
        CircuitBreakerOpen: circuit đang OPEN, block call
        LLMConnectionError: mất kết nối tới proxy (timeout/5xx/429 sau retry)
        LLMError: response sai format hoặc thiếu config
    """
    if not messages:
        raise ValueError("messages không được rỗng")
    for m in messages:
        # Tool messages / assistant tool_calls có thể không có 'content'
        if "role" not in m:
            raise ValueError(f"Mỗi message phải có 'role': {m}")

    use_model = model or settings.LLM_MODEL
    
    def _call():
        return _post_chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            model=use_model,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
        )
    
    # Gọi với circuit breaker nếu enabled
    if use_circuit_breaker:
        try:
            data = call_with_resilience(
                _call,
                circuit_breaker_name="llm_chat",
                max_retries=1,  # _post_chat_completion đã có retry
            )
        except CircuitBreakerOpen:
            # Circuit OPEN → raise để caller handle
            raise
    else:
        data = _call()

    try:
        choice = data["choices"][0]
        message = choice.get("message") or {}
        answer = message.get("content") or ""
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"Chat completion response thiếu 'choices[0].message': {data}") from e

    tool_calls = _parse_tool_calls(message)

    usage = data.get("usage") or {}
    return {
        "answer": answer,
        "tool_calls": tool_calls,
        "usage": {
            "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        },
        "raw": data,
    }


def _parse_tool_calls(message: Dict[str, Any]) -> Optional[List[Dict[str, Any]]]:
    """
    Parse 'tool_calls' từ message response (OpenAI-compatible).
    Arguments được decode từ JSON string -> dict. Bỏ qua call lỗi JSON.
    """
    raw_calls = message.get("tool_calls")
    if not raw_calls or not isinstance(raw_calls, list):
        return None

    import json as _json

    parsed: List[Dict[str, Any]] = []
    for call in raw_calls:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        raw_args = fn.get("arguments")
        if isinstance(raw_args, dict):
            args = raw_args
        elif isinstance(raw_args, str) and raw_args.strip():
            try:
                args = _json.loads(raw_args)
            except (ValueError, TypeError):
                logger.warning("Tool call '%s' có arguments không phải JSON hợp lệ: %s", name, raw_args[:200])
                args = {}
        else:
            args = {}
        parsed.append({"id": call.get("id"), "name": name, "arguments": args})

    return parsed or None


def safe_chat_completion(
    messages: List[Dict[str, str]],
    fallback: Optional[str] = None,
    **kwargs,
) -> Dict[str, Any]:
    """
    Wrapper có fallback message khi proxy lỗi, dùng cho UX-end-user.
    """
    try:
        return chat_completion(messages, **kwargs)
    except Exception as e:  # noqa: BLE001
        logger.error("LLM call failed, returning fallback: %s", e)
        return {
            "answer": fallback
            or "Xin lỗi, hiện tại trợ lý AI đang gặp sự cố. Bạn thử lại sau nhé.",
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
            "raw": {"error": str(e)},
        }


# ---------------------------------------------------------------------------
# Embedding API
# ---------------------------------------------------------------------------


def _embeddings_url() -> str:
    base = settings.GEMINI_PROXY_BASE_URL.rstrip("/")
    return f"{base}/embeddings"


def embed_text(
    text: str,
    model: Optional[str] = None,
    use_circuit_breaker: bool = True,
) -> List[float]:
    """
    Tạo embedding cho text qua Gemini proxy với circuit breaker.

    Args:
        text: input text
        model: override model (mặc định settings.EMBEDDING_MODEL)
        use_circuit_breaker: True = bật circuit breaker

    Returns:
        list[float] - vector embedding

    Raises:
        CircuitBreakerOpen: circuit đang OPEN
        LLMError: nếu call fail
    """
    if not text or not text.strip():
        raise ValueError("text không được rỗng")

    def _embed():
        return _embed_internal(text, model)
    
    if use_circuit_breaker:
        try:
            return call_with_resilience(
                _embed,
                circuit_breaker_name="llm_embedding",
                max_retries=1,
            )
        except CircuitBreakerOpen:
            raise
    else:
        return _embed()


def _embed_internal(
    text: str,
    model: Optional[str] = None,
) -> List[float]:
    """Internal embedding function (có retry logic)."""
    api_key = _require_api_key()
    url = _embeddings_url()
    use_model = model or settings.EMBEDDING_MODEL

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": use_model,
        "input": text,
    }

    last_err: Optional[Exception] = None
    transport_failed = False
    attempts = settings.GEMINI_PROXY_MAX_RETRIES + 1
    for attempt in range(1, attempts + 1):
        try:
            with httpx.Client(timeout=settings.GEMINI_PROXY_TIMEOUT) as client:
                resp = client.post(url, headers=headers, json=payload)
                if resp.status_code >= 500 or resp.status_code == 429:
                    transport_failed = True
                    last_err = httpx.HTTPStatusError(
                        f"{resp.status_code} {resp.text[:200]}",
                        request=resp.request,
                        response=resp,
                    )
                    logger.warning(
                        "Gemini embedding transient error (attempt %s/%s): %s",
                        attempt,
                        attempts,
                        last_err,
                    )
                    time.sleep(min(2 ** (attempt - 1), 5))
                    continue
                resp.raise_for_status()
                data = resp.json()
            break
        except (httpx.TimeoutException, httpx.TransportError) as e:
            transport_failed = True
            last_err = e
            logger.warning(
                "Gemini embedding transport error (attempt %s/%s): %s",
                attempt,
                attempts,
                e,
            )
            time.sleep(min(2 ** (attempt - 1), 5))
            continue
    else:
        if transport_failed:
            raise LLMConnectionError(
                f"Không kết nối được tới LLM proxy (embedding) sau {attempts} lần thử: {last_err}"
            )
        raise LLMError(f"Gemini embedding failed after {attempts} attempts: {last_err}")

    try:
        embedding = data["data"][0]["embedding"]
        if not isinstance(embedding, list):
            raise LLMError(f"Embedding response không phải list: {type(embedding)}")
        return [float(x) for x in embedding]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"Embedding response thiếu 'data[0].embedding': {data}") from e


def get_llm_status() -> dict:
    """Get LLM service status (monitoring endpoint)."""
    from app.services.llm_error_handler import get_circuit_breaker_status
    
    return {
        "circuit_breakers": get_circuit_breaker_status(),
        "proxy_url": settings.GEMINI_PROXY_BASE_URL,
        "default_model": settings.LLM_MODEL,
        "embedding_model": settings.EMBEDDING_MODEL,
    }


def reset_llm_circuit_breakers():
    """Reset all LLM circuit breakers (admin use)."""
    from app.services.llm_error_handler import reset_all_circuit_breakers
    reset_all_circuit_breakers()
    logger.info("All LLM circuit breakers reset")
