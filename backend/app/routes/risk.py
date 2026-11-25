import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response
from sqlalchemy.orm import Session

from app.middleware.auth import SCOPE_READ, SCOPE_WRITE, Principal, require_scope
from app.middleware.rate_limit import rate_limit
from app.routes.deps import get_db
from app.schemas.risk import (
    TXN_PATTERN,
    AuditResponse,
    ErrorResponse,
    InitiateRequest,
    InitiateResponse,
    StatsResponse,
    TransactionList,
)
from app.services import transactions as svc
from app.utils.url_validation import UnsafeCallbackURL, validate_callback_url

log = logging.getLogger("risk.api")
router = APIRouter(prefix="/api/v1/risk-score", tags=["Risk Score"])

AUTH_ERRORS = {
    401: {"model": ErrorResponse, "description": "Missing, invalid or expired bearer token"},
    403: {"model": ErrorResponse, "description": "Token valid but lacks required scope / partner binding"},
    429: {"model": ErrorResponse, "description": "Rate limit exceeded"},
}


@router.post(
    "/initiate",
    status_code=202,
    response_model=InitiateResponse,
    summary="Initiate a risk-score evaluation",
    description="Requires Bearer JWT with scope `write:risk_test`. The Aadhaar number (test data only) is "
    "masked before storage and is never logged or returned. Publishes a `Risk_Evaluation_Requested` event.",
    responses={**AUTH_ERRORS, 422: {"model": ErrorResponse, "description": "Validation error (input values are never echoed)"},
               503: {"model": ErrorResponse, "description": "Event bus unavailable"}},
    dependencies=[Depends(rate_limit("initiate", "rate_limit_initiate_per_minute"))],
)
def initiate(
    body: InitiateRequest,
    request: Request,
    principal: Annotated[Principal, Depends(require_scope(SCOPE_WRITE))],
    db: Session = Depends(get_db),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key", pattern=r"^[A-Za-z0-9._-]{8,100}$")] = None,
):
    settings = request.app.state.settings
    if body.partner_id != principal.partner_id:
        raise HTTPException(403, "partner_id does not match the authenticated partner")
    try:
        validate_callback_url(
            body.callback_url,
            allow_http=settings.allow_http_callbacks,
            allow_private=settings.allow_private_callbacks,
            resolve=settings.ssrf_dns_check,
        )
    except UnsafeCallbackURL as exc:
        raise HTTPException(422, f"callback_url rejected: {exc}") from None

    txn, created = svc.create_transaction(
        db,
        partner_id=principal.partner_id,
        aadhaar_number=body.aadhaar_number.get_secret_value(),
        device_data=body.device_data.model_dump(exclude_none=True),
        callback_url=body.callback_url,
        idempotency_header=idempotency_key,
    )
    if created:
        event = {
            "event_type": "Risk_Evaluation_Requested",
            "transaction_id": txn.transaction_id,
            "idempotency_key": txn.idempotency_key,
            "partner_id": txn.partner_id,
        }
        try:
            request.app.state.producer.publish(settings.kafka_topic, txn.transaction_id, event)
        except Exception:
            log.exception("failed to publish event for %s", txn.transaction_id)
            svc.mark_publish_failed(db, txn.transaction_id)
            raise HTTPException(503, "Event bus unavailable; transaction marked FAILED") from None
        log.info("transaction %s created for partner %s", txn.transaction_id, txn.partner_id)
    return InitiateResponse(transaction_id=txn.transaction_id, status=txn.status)


@router.get(
    "/audit/{transaction_id}",
    response_model=AuditResponse,
    summary="Audit a transaction (owner only)",
    description="Requires scope `read:risk_test`. The partner is taken from the token, never from the "
    "request. A transaction owned by another partner is indistinguishable from one that does not exist (404).",
    responses={**AUTH_ERRORS, 404: {"model": ErrorResponse, "description": "Not found (or not owned by caller)"}},
    dependencies=[Depends(rate_limit("read", "rate_limit_read_per_minute"))],
)
def audit(
    transaction_id: Annotated[str, Path(pattern=TXN_PATTERN)],
    principal: Annotated[Principal, Depends(require_scope(SCOPE_READ))],
    db: Session = Depends(get_db),
):
    row = svc.audit_lookup(db, transaction_id, principal.partner_id)
    if row is None:
        raise HTTPException(404, "Transaction not found")
    return row


@router.get(
    "/transactions",
    response_model=TransactionList,
    summary="List the caller's transactions",
    responses=AUTH_ERRORS,
    dependencies=[Depends(rate_limit("read", "rate_limit_read_per_minute"))],
)
def list_transactions(
    principal: Annotated[Principal, Depends(require_scope(SCOPE_READ))],
    db: Session = Depends(get_db),
    status: Literal["PENDING", "COMPLETED", "FAILED"] | None = Query(None, description="PENDING includes PROCESSING"),
    search: str | None = Query(None, max_length=40, pattern=r"^[A-Za-z0-9_-]*$"),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    items, total = svc.list_transactions(db, principal.partner_id, status=status, search=search or None, limit=limit, offset=offset)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get(
    "/stats",
    response_model=StatsResponse,
    summary="Dashboard counters for the caller's transactions",
    responses=AUTH_ERRORS,
    dependencies=[Depends(rate_limit("read", "rate_limit_read_per_minute"))],
)
def get_stats(principal: Annotated[Principal, Depends(require_scope(SCOPE_READ))], db: Session = Depends(get_db)):
    return svc.stats(db, principal.partner_id)
