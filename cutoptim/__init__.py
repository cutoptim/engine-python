"""cutoptim — the official client for the CutOptim Engine API (https://cutoptim.com/engine/reference).

Standard library only (urllib, hmac). Types are generated from the OpenAPI document (types_gen.py).

    from cutoptim import CutOptim
    client = CutOptim(api_key="co_test_...")
    plan = client.optimize_2d({"parts": [{"w": 600, "h": 400, "qty": 4}], "stock": [{"w": 2440, "h": 1220}]})
"""
from .client import CutOptim, CutOptimError, is_job_accepted
from .webhooks import verify_webhook, SIGNATURE_HEADER

__version__ = "1.0.0"
__all__ = ["CutOptim", "CutOptimError", "is_job_accepted", "verify_webhook", "SIGNATURE_HEADER", "__version__"]
