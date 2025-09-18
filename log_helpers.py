# /shared/log_helpers.py
from __future__ import annotations

import logging
import traceback
from time import perf_counter
from datetime import datetime, timezone
from typing import Any, Dict, Optional

try:
    # You should have this in Step 3
    from .request_context import get_context  # returns Dict[str, Any]
except Exception:  # fallback if import order changes during local tests
    def get_context() -> Dict[str, Any]:
        return {}

_LOGGER = logging.getLogger("app")  # align with your logging_config.py logger name


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _merge_dims(extra_dims: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge contextvars + caller-provided dims.
    If you're using python-json-logger, these become top-level JSON fields.
    If you're sending to App Insights via OpenCensus, consider nesting under
    'custom_dimensions' instead.
    """
    base = dict(get_context())
    if extra_dims:
        base.update(extra_dims)
    return base


def log_start(action: Optional[str] = None, extra_dims: Optional[Dict[str, Any]] = None) -> float:
    """
    Emits a 'start' event and returns a monotonic start time you can pass to success/error.
    Usage:
        t0 = log_start("GET /docs", {"endpoint": "/api/docs"})
    """
    t0 = perf_counter()
    dims = _merge_dims(extra_dims)
    if action:
        dims["action"] = action
    _LOGGER.info("start", extra=dims)
    return t0


def log_success(start_time: float, extra_dims: Optional[Dict[str, Any]] = None) -> None:
    """
    Emits a 'success' event with durationMs.
    """
    duration_ms = int((perf_counter() - start_time) * 1000)
    dims = _merge_dims(extra_dims)
    dims["durationMs"] = duration_ms
    dims["timestamp"] = _utc_iso()
    _LOGGER.info("success", extra=dims)


def log_error(
    start_time: Optional[float],
    exc: BaseException,
    extra_dims: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Emits an 'error' event with durationMs (if start_time provided) + stacktrace.
    Uses logger.exception to preserve traceback for local console & AI.
    """
    duration_ms = None
    if start_time is not None:
        duration_ms = int((perf_counter() - start_time) * 1000)

    dims = _merge_dims(extra_dims)
    if duration_ms is not None:
        dims["durationMs"] = duration_ms
    dims["timestamp"] = _utc_iso()
    dims["error"] = {
        "type": type(exc).__name__,
        "message": str(exc),
        "stack": traceback.format_exc(),
    }

    # .exception() logs at ERROR with current exc info
    _LOGGER.exception("error", extra=dims)
