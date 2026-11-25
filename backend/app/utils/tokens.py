"""Token minting for DEVELOPMENT/TEST only. Real tokens come from your identity provider."""
import time

import jwt

from app.config import Settings

DEV_PARTNERS = {
    "partner_a": {"partner_id": "PARTNER001", "scope": "write:risk_test read:risk_test", "label": "Partner A"},
    "partner_b": {"partner_id": "PARTNER002", "scope": "write:risk_test read:risk_test", "label": "Partner B"},
    "unauthorized": {"partner_id": "PARTNER999", "scope": "read:public", "label": "Unauthorized user"},
}


def make_token(settings: Settings, *, partner_id: str, scope: str, sub: str | None = None, ttl: int = 86400) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "sub": sub or f"user-{partner_id.lower()}",
            "partner_id": partner_id,
            "scope": scope,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": now,
            "exp": now + ttl,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def make_dev_tokens(settings: Settings) -> dict:
    return {
        key: {**{k: v for k, v in meta.items()}, "token": make_token(settings, partner_id=meta["partner_id"], scope=meta["scope"])}
        for key, meta in DEV_PARTNERS.items()
    }
