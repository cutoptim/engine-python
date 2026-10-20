"""Verify a CutOptim webhook delivery (the CutOptim-Signature header).

    CutOptim-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256(secret, "<t>.<raw body>")>[,v1=...]

Pass the RAW request body (the exact bytes received): a body parsed and serialised again does not match. During a
secret rotation the header carries two v1 values; either matching your secret is enough.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import time
from typing import Iterable, Optional, Union

SIGNATURE_HEADER = "CutOptim-Signature"
DEFAULT_TOLERANCE_S = 300

_T = re.compile(r"^\d{1,12}$")
_V1 = re.compile(r"^[0-9a-f]{64}$")


def verify_webhook(
    raw_body: Union[bytes, str],
    header: Optional[str],
    secrets: Union[str, Iterable[str]],
    tolerance_s: int = DEFAULT_TOLERANCE_S,
    now_s: Optional[int] = None,
) -> bool:
    """True when ``header`` signs ``raw_body`` with one of ``secrets`` inside the time window."""
    if not isinstance(header, str) or len(header) > 4096:
        return False
    t: Optional[int] = None
    v1 = []
    for part in header.split(","):
        k, sep, v = part.partition("=")
        if not sep or not k.strip():
            return False
        k, v = k.strip(), v.strip()
        if k == "t":
            if t is not None or not _T.match(v):
                return False
            t = int(v)
        elif k == "v1":
            if not _V1.match(v):
                return False
            v1.append(v)
    if t is None or not v1:
        return False
    now = int(time.time()) if now_s is None else now_s
    if abs(now - t) > tolerance_s:
        return False
    body = raw_body.encode("utf-8") if isinstance(raw_body, str) else raw_body
    for secret in [secrets] if isinstance(secrets, str) else list(secrets):
        want = hmac.new(secret.encode("utf-8"), str(t).encode("ascii") + b"." + body, hashlib.sha256).hexdigest()
        if any(hmac.compare_digest(want, got) for got in v1):
            return True
    return False
