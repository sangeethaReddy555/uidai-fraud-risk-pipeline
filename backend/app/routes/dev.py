"""DEVELOPMENT-ONLY helpers (mounted only when ENVIRONMENT=development and ENABLE_DEV_TOKENS=true).

* /api/v1/dev/tokens        sample JWTs for Partner A, Partner B and an unauthorized user.
                            THESE ARE NOT PRODUCTION CREDENTIALS and use the dev signing secret.
* /api/v1/dev/callback-sink a fake partner endpoint so the full pipeline can be demoed locally.
                            ?fail_first=N makes it answer 503 for the first N calls per transaction,
                            which demonstrates retry/backoff.
"""
from collections import defaultdict

from fastapi import APIRouter, Body, Query, Request

from app.utils.tokens import make_dev_tokens

router = APIRouter(prefix="/api/v1/dev", tags=["Development only"])
_calls: dict[str, int] = defaultdict(int)


@router.get("/tokens", summary="Sample development tokens (NOT production credentials)")
def dev_tokens(request: Request):
    return {
        "warning": "Development tokens signed with a development secret. Not production credentials.",
        "tokens": make_dev_tokens(request.app.state.settings),
    }


@router.post("/callback-sink", summary="Fake partner callback receiver")
def callback_sink(payload: dict = Body(...), fail_first: int = Query(0, ge=0, le=10)):
    from fastapi import HTTPException

    key = str(payload.get("transaction_id", "?"))
    _calls[key] += 1
    if _calls[key] <= fail_first:
        raise HTTPException(503, "simulated partner outage")
    return {"received": True, "attempts": _calls[key]}
