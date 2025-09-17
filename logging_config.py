# /shared/logging_config.py
import json
import logging
import os
import sys
from contextvars import ContextVar
from typing import Any

# ---- Correlation context (set in Step 3) ----
cv_process_id = ContextVar("processId", default=None)
cv_run_id = ContextVar("runId", default=None)
cv_triggered_by = ContextVar("triggeredBy", default=None)
cv_endpoint = ContextVar("endpoint", default=None)
cv_function = ContextVar("function", default=None)
cv_env = ContextVar("env", default=os.getenv("ENVIRONMENT", "local"))

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "message": record.getMessage(),
            # common dims
            "processId": cv_process_id.get(),
            "runId": cv_run_id.get(),
            "triggeredBy": cv_triggered_by.get(),
            "endpoint": cv_endpoint.get(),
            "function": cv_function.get(),
            "env": cv_env.get(),
        }

        # Fold in extras (flat, JSON-serializable only)
        for k, v in record.__dict__.items():
            if k in ("msg", "args", "levelname", "levelno", "created",
                     "msecs", "relativeCreated", "name", "module",
                     "pathname", "filename", "lineno", "funcName",
                     "exc_info", "exc_text", "stack_info"):  # skip std keys
                continue
            if k not in base and isinstance(v, (str, int, float, bool, type(None), dict, list, tuple)):
                base[k] = v

        return json.dumps(base, ensure_ascii=False)

_configured = False

def get_logger(name: str = "app") -> logging.Logger:
    """
    Returns a logger that outputs JSON to stdout.
    Azure Functions/Container Apps will ship this to App Insights when configured.
    """
    global _configured
    if not _configured:
        root = logging.getLogger()
        root.setLevel(os.getenv("LOG_LEVEL", "INFO"))

        # Replace handlers so local/dev doesn't double-log
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.handlers = [handler]

        _configured = True

    return logging.getLogger(name)
