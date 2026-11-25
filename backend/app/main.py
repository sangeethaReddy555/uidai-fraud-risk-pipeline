import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings, get_settings
from app.database import Base, make_engine, make_session_factory
from app.kafka import InMemoryBroker, build_consumer, build_producer
from app.middleware.rate_limit import SlidingWindowLimiter
from app.routes import dev, risk
from app.utils.logging import configure_logging
from app.workers.risk_worker import RiskWorker
from app.workers.runner import start_threads

log = logging.getLogger("risk.app")

DESCRIPTION = """
**UIDAI Sandbox – Fraud Risk Scoring Pipeline** (assignment project).

* Uses **fake/test Aadhaar numbers only**. Never connects to UIDAI or any real Aadhaar system.
* All endpoints need `Authorization: Bearer <JWT>`. In development, `GET /api/v1/dev/tokens` returns sample
  tokens for Partner A, Partner B and an unauthorized user (**not production credentials**).
* Errors: `401` unauthenticated, `403` forbidden (scope / partner mismatch), `404` not found or not owned,
  `422` validation, `429` rate limited, `503` event bus down.
"""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging()

    engine = make_engine(settings)
    session_factory = make_session_factory(engine)
    if settings.auto_create_tables:
        Base.metadata.create_all(engine)
    broker = InMemoryBroker() if settings.kafka_mode != "real" else None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop, threads = None, []
        if settings.embedded_worker:
            worker = RiskWorker(session_factory, settings)
            producer = app.state.producer
            stop, threads = start_threads(build_consumer(settings, broker), worker, producer, settings)
            log.info("embedded worker started (kafka_mode=%s)", settings.kafka_mode)
        yield
        if stop:
            stop.set()
            for t in threads:
                t.join(timeout=3)
        engine.dispose()

    app = FastAPI(title="UIDAI Sandbox – Fraud Risk Scoring API", version="1.0.0", description=DESCRIPTION, lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.broker = broker
    app.state.producer = build_producer(settings, broker)
    app.state.limiter = SlidingWindowLimiter()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        # Pydantic's default body echoes the offending `input` -> would leak Aadhaar numbers. Strip it.
        errors = [
            {"field": ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path", "header")), "message": e["msg"], "type": e["type"]}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": "Validation failed", "errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.error("unhandled error: %s", type(exc).__name__)  # class only; no payload/trace values
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    @app.get("/health", tags=["Health"], summary="Liveness probe")
    def health():
        return {"status": "ok"}

    app.include_router(risk.router)
    if settings.is_development and settings.enable_dev_tokens:
        app.include_router(dev.router)
    return app

