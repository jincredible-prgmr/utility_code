# syndigo_client_basic.py
from __future__ import annotations

import os
import time
import uuid
import json
import random
import logging
from typing import Any, Dict, Optional

import httpx

# ---------- Logging (key=value style) ----------
logger = logging.getLogger("syndigo")
handler = logging.StreamHandler()
formatter = logging.Formatter("%(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

def kvlog(level: int, **kwargs: Any) -> None:
    payload = {"ts": round(time.time(), 3), **kwargs}
    logger.log(level, " ".join(f"{k}={json.dumps(v)}" for k, v in payload.items()))

# ---------- Retry / Backoff helpers ----------
RETRYABLE_STATUS = {429, 502, 503, 504}
NON_RETRYABLE_STATUS = {400, 401, 403, 404, 409, 422}

def is_retryable(status_code: Optional[int], exc: Optional[Exception]) -> bool:
    if exc is not None:
        return True  # network/timeout/etc.
    return status_code in RETRYABLE_STATUS if status_code is not None else False

def backoff_delay(attempt: int, base: float = 0.5, cap: float = 4.0) -> float:
    exp = min(cap, base * (2 ** (attempt - 1)))
    return random.uniform(exp * 0.5, exp * 1.5)

# ---------- Syndigo Client (Basic Auth) ----------
class SyndigoClient:
    def __init__(
        self,
        base_url: str,
        client_id: str,
        client_secret: str,
        *,
        run_id: Optional[str] = None,
        max_attempts: int = 3,
        timeout: tuple[float, float] = (3.0, 8.0),  # (connect, read)
        user_agent: str = "syndigo-integration/1.0",
    ):
        self.base_url = base_url.rstrip("/")
        self.run_id = run_id or str(uuid.uuid4())
        self.max_attempts = max(1, max_attempts)
        self.timeout = httpx.Timeout(connect=timeout[0], read=timeout[1])
        self.user_agent = user_agent
        self._client = httpx.Client(
            timeout=self.timeout,
            auth=(client_id, client_secret),  # httpx.BasicAuth under the hood
        )

    def close(self) -> None:
        self._client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Any] = None,
        headers: Optional[Dict[str, str]] = None,
        idempotency_key: Optional[str] = None,
    ) -> httpx.Response:
        url = f"{self.base_url}/{path.lstrip('/')}"
        attempt = 1
        resp: Optional[httpx.Response] = None

        while True:
            request_id = str(uuid.uuid4())
            out_headers = {
                "User-Agent": self.user_agent,
                "X-Request-ID": request_id,
                "X-Run-ID": self.run_id,
                "Accept": "application/json",
            }
            if idempotency_key:
                out_headers["Idempotency-Key"] = idempotency_key
            if headers:
                out_headers.update(headers)

            status = None
            exc: Optional[Exception] = None
            retry_after_ms = 0
            started = time.time()

            try:
                resp = self._client.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    json=json_body,
                    headers=out_headers,
                )
                status = resp.status_code

                # Downstream correlation header (if any)
                syndigo_req_id = (
                    resp.headers.get("x-request-id")
                    or resp.headers.get("x-correlation-id")
                    or resp.headers.get("request-id")
                )

                # Retry-After handling on retryable statuses
                if status in RETRYABLE_STATUS:
                    ra = resp.headers.get("Retry-After")
                    if ra:
                        try:
                            retry_after_ms = int(float(ra) * 1000)
                        except ValueError:
                            retry_after_ms = 0

                duration_ms = int((time.time() - started) * 1000)
                size = len(resp.content or b"")

                kvlog(
                    logging.INFO if 200 <= status < 300 else logging.WARNING,
                    msg="http-attempt",
                    method=method.upper(),
                    endpoint=path,
                    status=status,
                    attempt=attempt,
                    max_attempts=self.max_attempts,
                    duration_ms=duration_ms,
                    result_size_bytes=size,
                    request_id=request_id,
                    run_id=self.run_id,
                    syndigo_request_id=syndigo_req_id,
                    retry_after_ms=retry_after_ms,
                )

                if 200 <= status < 300:
                    kvlog(
                        logging.INFO,
                        msg="http-success",
                        method=method.upper(),
                        endpoint=path,
                        attempts=attempt,
                        status=status,
                        duration_ms=duration_ms,
                        request_id=request_id,
                        run_id=self.run_id,
                    )
                    return resp

                # Non-retryable → return immediately
                if status in NON_RETRYABLE_STATUS:
                    return resp

            except Exception as e:
                exc = e
                duration_ms = int((time.time() - started) * 1000)
                kvlog(
                    logging.WARNING,
                    msg="http-exception",
                    method=method.upper(),
                    endpoint=path,
                    attempt=attempt,
                    max_attempts=self.max_attempts,
                    duration_ms=duration_ms,
                    error=str(e.__class__.__name__),
                    request_id=request_id,
                    run_id=self.run_id,
                )

            # Decide to retry
            if attempt >= self.max_attempts or not is_retryable(status, exc):
                if resp is not None:
                    return resp
                raise RuntimeError(f"HTTP call failed without response: {exc}")

            # Delay before retry
            if retry_after_ms > 0:
                delay = min(10_000, retry_after_ms) / 1000.0
            else:
                delay = backoff_delay(attempt)

            kvlog(
                logging.WARNING,
                msg="http-retry",
                method=method.upper(),
                endpoint=path,
                next_delay_ms=int(delay * 1000),
                attempt=attempt,
                max_attempts=self.max_attempts,
                run_id=self.run_id,
            )
            time.sleep(delay)
            attempt += 1

    # Convenience wrappers
    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)


# ---------- Example usage ----------
def _env(name: str, required: bool = True, default: Optional[str] = None) -> str:
    v = os.getenv(name, default)
    if required and not v:
        raise RuntimeError(f"Missing env var: {name}")
    return v  # type: ignore

if __name__ == "__main__":
    """
    Set these in your environment (or .env loaded by python-dotenv):
      SYNDIGO_BASE_URL=https://api.syndigo.com/v1
      SYNDIGO_CLIENT_ID=...
      SYNDIGO_CLIENT_SECRET=...
    """
    client = SyndigoClient(
        base_url=_env("SYNDIGO_BASE_URL"),
        client_id=_env("SYNDIGO_CLIENT_ID"),
        client_secret=_env("SYNDIGO_CLIENT_SECRET"),
    )

    try:
        # Safest read-only probe; replace "/configs" with your actual endpoint.
        resp = client.get("/configs", params={"pageSize": 5})
        print("Status:", resp.status_code)
        print("Body:", resp.text[:500])
    finally:
        client.close()
