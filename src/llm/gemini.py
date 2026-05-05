"""Gemini LLM wrapper with transient-error retry and Flash fallback."""
from __future__ import annotations

import logging
import random
import time
from functools import wraps
from typing import Any, Callable, List, Optional

from langchain_core.messages import BaseMessage

from src import settings

logger = logging.getLogger(__name__)


# --- Retry decorator -------------------------------------------------------

_TRANSIENT_TOKENS = (
    "rate limit",
    "rate_limit",
    "rate-limit",
    "resource_exhausted",
    "deadline_exceeded",
    "timeout",
    "503",
    "502",
    "500",
    "unavailable",
    "internal error",
)


def _is_transient(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return any(token in msg for token in _TRANSIENT_TOKENS)


def with_retries(max_attempts: int = settings.LLM_RETRY_LIMIT, base_delay: float = 0.5):
    """Exponential-backoff retry for transient LLM errors."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            last_exc: Optional[BaseException] = None
            while attempt < max_attempts:
                try:
                    return fn(*args, **kwargs)
                except Exception as e:  # noqa: BLE001
                    last_exc = e
                    if not _is_transient(e):
                        raise
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 0.3)
                    logger.warning(
                        "Transient LLM error on attempt %d/%d (%s). Sleeping %.2fs",
                        attempt + 1,
                        max_attempts,
                        e,
                        delay,
                    )
                    time.sleep(delay)
                    attempt += 1
            assert last_exc is not None
            raise last_exc

        return wrapper

    return decorator


# --- LLM construction ------------------------------------------------------

# Lazy imports so tests can monkeypatch without requiring credentials.

def _build_chat(model_name: str, temperature: float = 0.0):
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=model_name,
        temperature=temperature,
        google_api_key=settings.GOOGLE_API_KEY or None,
    )


class GeminiLLM:
    """Two-tier LLM: tries `pro` first, falls back to `flash` on hard failure."""

    def __init__(self, primary: str | None = None, fallback: str | None = None, temperature: float = 0.0):
        self.primary_name = primary or settings.GEMINI_MODEL_PRO
        self.fallback_name = fallback or settings.GEMINI_MODEL_FLASH
        self.temperature = temperature
        self._primary = None
        self._fallback = None

    @property
    def primary(self):
        if self._primary is None:
            self._primary = _build_chat(self.primary_name, self.temperature)
        return self._primary

    @property
    def fallback(self):
        if self._fallback is None:
            self._fallback = _build_chat(self.fallback_name, self.temperature)
        return self._fallback

    @with_retries()
    def _invoke_primary(self, messages: List[BaseMessage]):
        return self.primary.invoke(messages)

    @with_retries()
    def _invoke_fallback(self, messages: List[BaseMessage]):
        return self.fallback.invoke(messages)

    def invoke(self, messages: List[BaseMessage]):
        try:
            return self._invoke_primary(messages)
        except Exception as e:  # noqa: BLE001
            logger.error("Primary model %s failed (%s) — falling back to %s", self.primary_name, e, self.fallback_name)
            return self._invoke_fallback(messages)


def build_embeddings():
    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    return GoogleGenerativeAIEmbeddings(
        model=f"models/{settings.GEMINI_EMBEDDING_MODEL}",
        google_api_key=settings.GOOGLE_API_KEY or None,
    )
