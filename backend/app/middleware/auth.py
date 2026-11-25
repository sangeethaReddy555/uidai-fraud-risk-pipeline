"""Bearer-token (JWT) authentication and scope-based authorization.

401 -> missing / malformed / expired / badly-signed token (caller is not authenticated)
403 -> token is valid but lacks the required scope or partner binding
"""
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings

bearer_scheme = HTTPBearer(auto_error=False, description="JWT Bearer token")

SCOPE_WRITE = "write:risk_test"
SCOPE_READ = "read:risk_test"


@dataclass(frozen=True)
class Principal:
    subject: str
    partner_id: str
    scopes: frozenset[str]


def _unauthorized(msg: str) -> HTTPException:
    return HTTPException(status_code=401, detail=msg, headers={"WWW-Authenticate": "Bearer"})


def decode_token(token: str, settings: Settings) -> Principal:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],  # pinned: blocks alg=none / alg confusion
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.PyJWTError:
        raise _unauthorized("Invalid or expired token") from None
    partner_id = claims.get("partner_id")
    if not isinstance(partner_id, str) or not partner_id:
        raise _unauthorized("Invalid or expired token")
    scope = claims.get("scope", "")
    scopes = frozenset(scope.split()) if isinstance(scope, str) else frozenset()
    return Principal(subject=str(claims["sub"]), partner_id=partner_id, scopes=scopes)


def get_principal(
    request: Request, creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)
) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise _unauthorized("Missing bearer token")
    return decode_token(creds.credentials, request.app.state.settings)


def require_scope(scope: str):
    def dep(principal: Principal = Depends(get_principal)) -> Principal:
        if scope not in principal.scopes:
            raise HTTPException(status_code=403, detail=f"Missing required scope: {scope}")
        return principal

    return dep
