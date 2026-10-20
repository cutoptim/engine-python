"""The CutOptim Engine API client (standard library only).

* Every optimize call carries an Idempotency-Key (yours, or a generated UUID), so retries are never charged twice and
  never queue a second max job.
* 429 / 503 / 409 idempotency_in_progress / network errors are retried (default 2 times), honouring Retry-After.
* A non-2xx answer raises CutOptimError with the API's stable ``code`` — branch on it, never on the message.
* engine "max" answers 202 with a jobId: ``client.wait_for_job(job_id)`` — or register a webhook.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, Optional

from . import types_gen as t

_DEFAULT_BASE = "https://api.cutoptim.com"


class CutOptimError(Exception):
    """A non-2xx answer. ``code`` is the stable error (``invalid_request``, ``quota_exceeded``, ...)."""

    def __init__(self, status: int, code: str, message: str, details: Any = None, retry_after: Optional[int] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.details = details
        self.retry_after = retry_after


def is_job_accepted(result: Any) -> bool:
    """True when an optimize answer is the async 202 of engine "max"."""
    return isinstance(result, dict) and isinstance(result.get("jobId"), str) and result.get("status") == "queued"


class CutOptim:
    def __init__(self, api_key: Optional[str] = None, base_url: str = _DEFAULT_BASE, max_retries: int = 2, timeout_s: float = 30.0):
        from . import __version__

        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.timeout_s = timeout_s
        self._ua = "cutoptim-engine-python/" + __version__

    # ── optimize (metered) ──
    def optimize_2d(self, request: t.Optimize2DRequest, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """2D panels. engine "max" returns the 202 job (see wait_for_job)."""
        return self._call("POST", "/v1/optimize/2d", request, idempotency_key, idempotent=True)

    def optimize_1d(self, request: t.Optimize1DRequest, idempotency_key: Optional[str] = None) -> t.Optimize1DResponse:
        return self._call("POST", "/v1/optimize/1d", request, idempotency_key, idempotent=True)

    def optimize_wood(self, request: t.OptimizeWoodRequest, idempotency_key: Optional[str] = None) -> t.OptimizeWoodResponse:
        return self._call("POST", "/v1/optimize/wood", request, idempotency_key, idempotent=True)

    def optimize_nest(self, request: t.OptimizeNestRequest, idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        """True-shape nesting. engine "max" returns the 202 job."""
        return self._call("POST", "/v1/optimize/nest", request, idempotency_key, idempotent=True)

    # ── free / account ──
    def validate_2d(self, request: t.Optimize2DRequest) -> t.ValidateResponse:
        return self._call("POST", "/v1/validate/2d", request)

    def validate_1d(self, request: t.Optimize1DRequest) -> t.ValidateResponse:
        return self._call("POST", "/v1/validate/1d", request)

    def validate_wood(self, request: t.OptimizeWoodRequest) -> t.ValidateResponse:
        return self._call("POST", "/v1/validate/wood", request)

    def validate_nest(self, request: t.OptimizeNestRequest) -> t.ValidateResponse:
        return self._call("POST", "/v1/validate/nest", request)

    def import_nest(self, request: t.NestImportRequest) -> t.NestImportResponse:
        return self._call("POST", "/v1/import/nest", request)

    def get_job(self, job_id: str) -> Dict[str, Any]:
        return self._call("GET", "/v1/jobs/" + urllib.parse.quote(job_id, safe=""))

    def usage(self) -> t.UsageResponse:
        return self._call("GET", "/v1/usage")

    def health(self) -> t.HealthResponse:
        return self._call("GET", "/v1/health")

    def wait_for_job(self, job_id: str, timeout_s: float = 300.0, interval_s: float = 2.0) -> Dict[str, Any]:
        """Poll GET /v1/jobs/{id} (no quota) until the job succeeded or failed."""
        deadline = time.monotonic() + timeout_s
        wait = interval_s
        while True:
            job = self.get_job(job_id)
            if job.get("status") in ("succeeded", "failed"):
                return job
            if time.monotonic() + wait > deadline:
                raise CutOptimError(0, "timeout", "job %s is still %s after the wait timeout" % (job_id, job.get("status")))
            time.sleep(wait)
            wait = min(wait * 1.5, 10.0)

    # ── transport ──
    def _call(self, method: str, path: str, body: Any = None, idempotency_key: Optional[str] = None, idempotent: bool = False) -> Any:
        headers = {"Accept": "application/json", "User-Agent": self._ua}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
        if idempotent:
            # One key for the whole call, retries included.
            headers["Idempotency-Key"] = idempotency_key or str(uuid.uuid4())
        attempt = 0
        while True:
            req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_s) as res:
                    text = res.read().decode("utf-8")
                    return json.loads(text) if text else None
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "replace")
                try:
                    payload = json.loads(text) if text else None
                except ValueError:
                    payload = None
                retry_after = _int(e.headers.get("Retry-After"))
                code = payload.get("error") if isinstance(payload, dict) and isinstance(payload.get("error"), str) else "http_%d" % e.code
                retryable = e.code in (429, 503) or (e.code == 409 and code == "idempotency_in_progress")
                if retryable and attempt < self.max_retries:
                    time.sleep(_backoff(attempt, retry_after))
                    attempt += 1
                    continue
                message = payload.get("message") if isinstance(payload, dict) and isinstance(payload.get("message"), str) else "HTTP %d" % e.code
                details = payload.get("details") if isinstance(payload, dict) else None
                raise CutOptimError(e.code, code, message, details, retry_after) from None
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                if attempt >= self.max_retries:
                    raise
                time.sleep(_backoff(attempt, None))
                attempt += 1


def _int(v: Optional[str]) -> Optional[int]:
    try:
        return int(v) if v else None
    except ValueError:
        return None


def _backoff(attempt: int, retry_after: Optional[int]) -> float:
    if retry_after:
        return float(min(retry_after, 60))
    return min(0.5 * (2 ** attempt), 8.0)
