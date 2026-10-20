<p align="center">
  <a href="https://cutoptim.com/engine"><img src="https://raw.githubusercontent.com/cutoptim/engine-python/main/.github/logo.png" width="88" height="88" alt="CutOptim"></a>
</p>

<h1 align="center">CutOptim Engine API — Python SDK</h1>

<p align="center">
  Cutting optimization over HTTPS: <b>2D panels</b>, <b>1D linear</b>, <b>timber</b> and <b>true-shape nesting</b>.<br>
  Deterministic plans, saw-ready cut sequences — standard library only.
</p>

<p align="center">
  <a href="https://pypi.org/project/cutoptim/"><img alt="PyPI" src="https://img.shields.io/pypi/v/cutoptim?color=f0c040&labelColor=0d0f14&label=pypi"></a>
  <a href="https://github.com/cutoptim/engine-python/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/cutoptim/engine-python/actions/workflows/ci.yml/badge.svg"></a>
  <img alt="Python 3.9+" src="https://img.shields.io/badge/python-%E2%89%A53.9-f0c040?labelColor=0d0f14">
  <img alt="Zero dependencies" src="https://img.shields.io/badge/dependencies-0-f0c040?labelColor=0d0f14">
  <a href="https://github.com/cutoptim/engine-python/blob/main/LICENSE"><img alt="MIT" src="https://img.shields.io/badge/license-MIT-f0c040?labelColor=0d0f14"></a>
</p>

<p align="center">
  <a href="https://cutoptim.com/engine/reference/quickstart">Quickstart</a> ·
  <a href="https://cutoptim.com/engine/reference">API reference</a> ·
  <a href="https://cutoptim.com/engine/reference/guides/webhooks">Webhooks</a> ·
  <a href="https://cutoptim.com/engine/reference/changelog">Changelog</a> ·
  <a href="https://cutoptim.com/dashboard#api-keys">Get an API key</a>
</p>

---

## Why this SDK

- **Typed from the contract.** Request and response shapes are `TypedDict`s generated from the [OpenAPI 3.1 document](https://cutoptim.com/engine/openapi.json) — mypy and your editor know every field.
- **No dependencies.** `urllib`, `json` and `hmac` from the standard library; Python 3.9+.
- **Retries that never cost twice.** Every optimize call carries an `Idempotency-Key`; a retried call returns the stored answer instead of a second charge.
- **Async jobs without the boilerplate.** `wait_for_job()` polls the `max` engine for you — or let a webhook tell you.
- **Webhook verification built in.** `verify_webhook()` checks the signature on the raw body, with the replay window and secret rotation handled.

## Install

```bash
pip install cutoptim
```

A free **test key** (`co_test_…`, never billed) is enough to build the whole integration — create one on your [dashboard](https://cutoptim.com/dashboard#api-keys).

## Quickstart

```python
import os
from cutoptim import CutOptim, is_job_accepted

client = CutOptim(api_key=os.environ["CUTOPTIM_KEY"])

plan = client.optimize_2d({
    "parts": [
        {"name": "Side", "w": 720, "h": 560, "qty": 2},
        {"name": "Shelf", "w": 764, "h": 540, "qty": 3, "rotatable": False},
    ],
    "stock": [{"w": 2800, "h": 2070, "price": 48}],
    "options": {"kerf": 4},
})

if not is_job_accepted(plan):
    print(f"{plan['metrics']['sheetCount']} sheet(s), {plan['metrics']['yieldPct']}% yield")
    for sheet in plan["sheets"]:
        for p in sheet["parts"]:
            print(p["name"], p["x"], p["y"], p["w"], p["h"], "rotated" if p["rotated"] else "")
```

The same input always returns the same plan — cache it, test against it, quote from it.

## Every mode

```python
# 1D linear — bars, profiles, tubes
bars = client.optimize_1d({"parts": [{"name": "Rail", "length": 1200, "qty": 6}], "stock": [{"length": 6000}]})
print(bars["metrics"]["rodCount"], bars["metrics"]["yieldPct"])

# Timber — lengths cut from beams of a given cross-section (sw × sh)
timber = client.optimize_wood({
    "parts": [{"name": "Joist", "sw": 45, "sh": 145, "length": 3600, "qty": 4}],
    "stock": [{"sw": 45, "sh": 145, "length": 4800}],
})

# True-shape nesting — polygons (or SVG/DXF sources) on sheets
nest = client.optimize_nest({
    "parts": [{"name": "Bracket", "polygon": [[0, 0], [120, 0], [120, 40], [40, 120], [0, 120]], "qty": 10}],
    "stock": [{"w": 1000, "h": 500}],
})
if not is_job_accepted(nest):
    print(nest["metrics"]["sheetCount"], nest["metrics"]["density"])
```

Check a request without spending a call — the validate endpoints need no key and give the same verdict:

```python
CutOptim().validate_2d(request)  # {"valid": True, "warnings": [...]} or CutOptimError(400)
```

## Async `max` jobs

`"engine": "max"` searches harder (seconds to a minute) and answers `202` with a job id instead of a plan:

```python
accepted = client.optimize_2d({**request, "engine": "max"})
if is_job_accepted(accepted):
    job = client.wait_for_job(accepted["jobId"], timeout_s=300)  # polls GET /v1/jobs/{id}, no quota
    if job["status"] == "succeeded":
        print(job["result"])
```

## Webhooks

Instead of polling, register an endpoint on your [dashboard](https://cutoptim.com/dashboard#api-webhooks) and receive a signed `POST` (`job.succeeded` / `job.failed`) when a `max` job finishes. Verify it on the **raw** body:

```python
# Flask
from flask import Flask, request
from cutoptim import verify_webhook

@app.post("/cutoptim/webhook")
def cutoptim_webhook():
    if not verify_webhook(request.get_data(), request.headers.get("CutOptim-Signature"), WEBHOOK_SECRET):
        return "", 400
    event = request.get_json()   # deduplicate on event["id"] — delivery is at least once
    return "", 204               # answer within 10 s, then do the work
```

```python
# FastAPI
from fastapi import FastAPI, Request, Response

@app.post("/cutoptim/webhook")
async def cutoptim_webhook(request: Request):
    raw = await request.body()
    if not verify_webhook(raw, request.headers.get("CutOptim-Signature"), WEBHOOK_SECRET):
        return Response(status_code=400)
    return Response(status_code=204)
```

During a secret rotation both secrets sign for 24 hours — pass both: `verify_webhook(raw, header, [new_secret, old_secret])`.

## Retries and idempotency

| Situation | What the client does |
|---|---|
| `429 busy`, `503`, network error | retries (2× by default), waiting `Retry-After` when the API sends it |
| `409 idempotency_in_progress` | retries — the first request is still running; the retry receives its answer |
| any optimize call | sends an `Idempotency-Key` (a fresh UUID, or yours) — the **same** key on every retry |

Pass your own key to make retries safe across process restarts too:

```python
client.optimize_nest(request, idempotency_key=f"order-{order_id}")
```

Within 24 hours the same key and request return the stored answer — not charged again, and a `max` job is not queued twice.

## Errors

Any non-2xx answer raises `CutOptimError`:

```python
from cutoptim import CutOptimError

try:
    client.optimize_2d(request)
except CutOptimError as e:
    print(e.status, e.code, e.details, e.retry_after)  # branch on e.code, never on the message
```

| `code` | Status | Meaning |
|---|---|---|
| `invalid_request` | 400 | the request is wrong — `details["path"]` names the field; never charged |
| `unauthorized` | 401 | missing or unknown API key |
| `quota_exceeded` | 402 | the account's monthly quota is used up — `retry_after` counts to the reset |
| `key_revoked` | 403 | the key is revoked, or the API subscription is not active |
| `idempotency_conflict` | 409 | the key was used for a different request — use a new key |
| `too_large` | 413 | an input cap was exceeded (parts, rows, body size) |
| `busy` | 429 | at capacity right now — retried automatically |
| `service_unavailable` | 503 | an engine is not available on this deployment |
| `solve_timeout` | 504 | the nesting solve ran out of time |
| `timeout` | — | `wait_for_job()` gave up waiting (the job keeps running) |

A network failure that outlasts the retries is raised as the underlying `urllib.error.URLError`. The full list is on the [errors page](https://cutoptim.com/engine/reference/errors).

## Configuration

```python
CutOptim(
    api_key="co_live_…",                   # not needed for health() and validate_*()
    base_url="https://api.cutoptim.com",   # default
    max_retries=2,                         # 429 / 503 / 409 in-progress / network errors
    timeout_s=30.0,                        # per request
)
```

## API coverage

| Method | Endpoint | Quota |
|---|---|---|
| `optimize_2d(req, idempotency_key=None)` | `POST /v1/optimize/2d` | 1 call |
| `optimize_1d(req, idempotency_key=None)` | `POST /v1/optimize/1d` | 1 call |
| `optimize_wood(req, idempotency_key=None)` | `POST /v1/optimize/wood` | 1 call |
| `optimize_nest(req, idempotency_key=None)` | `POST /v1/optimize/nest` | 1 call |
| `validate_2d` · `validate_1d` · `validate_wood` · `validate_nest` | `POST /v1/validate/*` | free, no key |
| `import_nest(req)` | `POST /v1/import/nest` | free (key required) |
| `get_job(id)` · `wait_for_job(id)` | `GET /v1/jobs/{id}` | free |
| `usage()` | `GET /v1/usage` | free |
| `health()` | `GET /v1/health` | free, no key |

## Versioning

The SDK follows semver. The API is `v1` and only grows within it: a new field, endpoint or option arrives as a **minor** SDK release with the regenerated types; nothing you use today is removed or narrowed. See [versioning and stability](https://cutoptim.com/engine/reference/versioning) and the [API changelog](https://cutoptim.com/engine/reference/changelog) (also as RSS).

## Support

- Questions and bugs: [GitHub issues](https://github.com/cutoptim/engine-python/issues) or [support@cutoptim.com](mailto:support@cutoptim.com)
- Limits and quotas: [cutoptim.com/engine/reference/limits](https://cutoptim.com/engine/reference/limits)

This repository is published from the CutOptim monorepo; pull requests are welcome and applied upstream.

## License

[MIT](https://github.com/cutoptim/engine-python/blob/main/LICENSE) © CutOptim
