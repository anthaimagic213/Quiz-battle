"""
LLM Error Handler - Circuit breaker, retry logic, fallback.

Xử lý các trường hợp:
- Connection timeout
- Rate limit (429)
- Server error (500, 503)
- Model unavailable
- Invalid response

Flow:
1. Retry với exponential backoff (tối đa 3 lần)
2. Circuit breaker: sau N lần fail liên tiếp → OPEN (skip LLM call)
3. Fallback: trả về default response khi circuit OPEN
"""

import logging
import time
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(str, Enum):
    CLOSED = "closed"  # bình thường, cho phép gọi
    OPEN = "open"  # fail nhiều, block tất cả calls
    HALF_OPEN = "half_open"  # thử lại sau timeout


class CircuitBreaker:
    """
    Circuit breaker pattern cho LLM calls.
    
    - Sau {failure_threshold} lần fail liên tiếp → OPEN
    - OPEN trong {timeout_seconds} giây → chuyển HALF_OPEN
    - HALF_OPEN: cho phép 1 call thử → success → CLOSED, fail → OPEN
    """
    
    def __init__(
        self,
        name: str = "llm",
        failure_threshold: int = 5,
        timeout_seconds: int = 60,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time: datetime | None = None
        self.success_count_half_open = 0
    
    def call(self, func: Callable[[], T]) -> T:
        """
        Execute function với circuit breaker protection.
        
        Raises:
            CircuitBreakerOpen: khi circuit đang OPEN
            Exception: original exception từ func
        """
        if self.state == CircuitState.OPEN:
            # Check timeout để chuyển sang HALF_OPEN
            if self._should_attempt_reset():
                logger.info(f"Circuit breaker [{self.name}] OPEN → HALF_OPEN (timeout reached)")
                self.state = CircuitState.HALF_OPEN
            else:
                # Vẫn OPEN → raise
                logger.warning(
                    f"Circuit breaker [{self.name}] is OPEN. "
                    f"Blocking call until {self._get_reset_time()}"
                )
                raise CircuitBreakerOpen(
                    f"Circuit breaker [{self.name}] is OPEN. "
                    f"Try again after {self.timeout_seconds}s."
                )
        
        try:
            result = func()
            self._on_success()
            return result
        except Exception as e:
            self._on_failure()
            raise
    
    def _should_attempt_reset(self) -> bool:
        """Check xem đã đủ timeout chưa."""
        if not self.last_failure_time:
            return True
        elapsed = (datetime.now(timezone.utc) - self.last_failure_time).total_seconds()
        return elapsed >= self.timeout_seconds
    
    def _get_reset_time(self) -> str:
        """Trả về thời gian reset dự kiến."""
        if not self.last_failure_time:
            return "unknown"
        reset_at = self.last_failure_time + timedelta(seconds=self.timeout_seconds)
        return reset_at.strftime("%H:%M:%S")
    
    def _on_success(self):
        """Call thành công."""
        if self.state == CircuitState.HALF_OPEN:
            logger.info(f"Circuit breaker [{self.name}] HALF_OPEN → CLOSED (call success)")
            self.state = CircuitState.CLOSED
            self.failure_count = 0
        elif self.state == CircuitState.CLOSED:
            # Reset failure count
            self.failure_count = 0
    
    def _on_failure(self):
        """Call thất bại."""
        self.failure_count += 1
        self.last_failure_time = datetime.now(timezone.utc)
        
        if self.state == CircuitState.HALF_OPEN:
            # Fail trong HALF_OPEN → quay lại OPEN
            logger.warning(
                f"Circuit breaker [{self.name}] HALF_OPEN → OPEN "
                f"(test call failed)"
            )
            self.state = CircuitState.OPEN
        elif self.failure_count >= self.failure_threshold:
            # Vượt ngưỡng → OPEN
            logger.error(
                f"Circuit breaker [{self.name}] CLOSED → OPEN "
                f"(failures={self.failure_count}/{self.failure_threshold})"
            )
            self.state = CircuitState.OPEN
    
    def reset(self):
        """Manually reset circuit (admin use)."""
        logger.info(f"Circuit breaker [{self.name}] manually reset")
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None


class CircuitBreakerOpen(Exception):
    """Raised khi circuit breaker đang OPEN."""
    pass


# Global circuit breakers
_circuit_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str = "llm") -> CircuitBreaker:
    """Get or create circuit breaker instance."""
    if name not in _circuit_breakers:
        _circuit_breakers[name] = CircuitBreaker(name=name)
    return _circuit_breakers[name]


def retry_with_backoff(
    func: Callable[[], T],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retryable_exceptions: tuple = (Exception,),
) -> T:
    """
    Retry function với exponential backoff.
    
    Args:
        func: function cần retry
        max_retries: số lần retry tối đa
        initial_delay: delay ban đầu (giây)
        backoff_factor: nhân tử tăng delay (2 = double mỗi lần)
        retryable_exceptions: tuple exceptions cho phép retry
    
    Returns:
        result của func
    
    Raises:
        Exception: lỗi cuối cùng nếu hết retry
    """
    delay = initial_delay
    last_exception = None
    
    for attempt in range(max_retries):
        try:
            return func()
        except retryable_exceptions as e:
            last_exception = e
            
            # Kiểm tra xem có nên retry không
            if not _is_retryable_error(e):
                logger.warning(f"Non-retryable error: {type(e).__name__}: {e}")
                raise
            
            if attempt < max_retries - 1:
                logger.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed: "
                    f"{type(e).__name__}: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
                delay *= backoff_factor
            else:
                logger.error(
                    f"All {max_retries} attempts failed. "
                    f"Last error: {type(e).__name__}: {e}"
                )
    
    # Hết retry → raise lỗi cuối
    raise last_exception  # type: ignore


def _is_retryable_error(error: Exception) -> bool:
    """
    Check xem error có nên retry không.
    
    Retryable:
    - Timeout
    - Connection error
    - 5xx server error
    - Rate limit (429)
    
    Non-retryable:
    - 4xx client error (trừ 429)
    - Invalid API key
    - Model not found
    """
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()
    
    # Timeout errors
    if any(x in error_type for x in ["timeout", "timeouterror"]):
        return True
    
    # Connection errors
    if any(x in error_type for x in ["connectionerror", "connecttimeout"]):
        return True
    
    # HTTP errors
    if "429" in error_str or "rate limit" in error_str:
        return True
    
    if any(x in error_str for x in ["500", "502", "503", "504"]):
        return True
    
    # Non-retryable
    if any(x in error_str for x in [
        "401", "403",  # auth error
        "invalid api key",
        "model not found",
        "400",  # bad request
    ]):
        return False
    
    # Default: retry
    return True


def call_with_resilience(
    func: Callable[[], T],
    circuit_breaker_name: str = "llm",
    max_retries: int = 3,
    fallback: Callable[[], T] | None = None,
) -> T:
    """
    Gọi function với đầy đủ resilience: circuit breaker + retry + fallback.
    
    Flow:
    1. Check circuit breaker
    2. Retry với backoff
    3. Nếu fail hết → fallback (nếu có)
    
    Args:
        func: function cần gọi
        circuit_breaker_name: tên circuit breaker
        max_retries: số lần retry
        fallback: function fallback khi fail
    
    Returns:
        result của func hoặc fallback
    
    Raises:
        Exception: nếu không có fallback
    """
    cb = get_circuit_breaker(circuit_breaker_name)
    
    try:
        # Wrap trong circuit breaker
        def wrapped():
            return retry_with_backoff(
                func,
                max_retries=max_retries,
            )
        
        return cb.call(wrapped)
    
    except CircuitBreakerOpen as e:
        logger.error(f"Circuit breaker open: {e}")
        if fallback:
            logger.info("Using fallback function")
            return fallback()
        raise
    
    except Exception as e:
        logger.exception(f"Call failed after retries: {e}")
        if fallback:
            logger.info("Using fallback function")
            return fallback()
        raise


def reset_all_circuit_breakers():
    """Reset tất cả circuit breakers (admin endpoint)."""
    for name, cb in _circuit_breakers.items():
        cb.reset()
    logger.info(f"Reset {len(_circuit_breakers)} circuit breakers")


def get_circuit_breaker_status() -> dict[str, dict]:
    """Lấy status của tất cả circuit breakers (monitoring)."""
    return {
        name: {
            "state": cb.state.value,
            "failure_count": cb.failure_count,
            "last_failure_time": (
                cb.last_failure_time.isoformat()
                if cb.last_failure_time
                else None
            ),
        }
        for name, cb in _circuit_breakers.items()
    }
