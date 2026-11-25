"""HTTP callback delivery + outcome classification."""
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.config import Settings
from app.utils.url_validation import UnsafeCallbackURL, validate_callback_url

log = logging.getLogger("risk.callback")

TEMPORARY_STATUSES = {408, 425, 429}


@dataclass
class CallbackResult:
    status_code: int | None = None
    error: str | None = None
    blocked: bool = False  # SSRF guard rejected the URL: permanent


class CallbackSender(Protocol):
    def send(self, url: str, payload: dict) -> CallbackResult: ...


def classify(result: CallbackResult) -> str:
    """'success' | 'temporary' (retry with backoff) | 'permanent' (give up)."""
    if result.blocked:
        return "permanent"
    if result.status_code is None:  # timeout / connection error
        return "temporary"
    if 200 <= result.status_code < 300:
        return "success"
    if result.status_code >= 500 or result.status_code in TEMPORARY_STATUSES:
        return "temporary"  # includes 503
    return "permanent"  # other 4xx, unexpected 3xx (redirects are not followed)


class HttpCallbackSender:
    def __init__(self, settings: Settings):
        self.settings = settings

    def send(self, url: str, payload: dict) -> CallbackResult:
        try:  # re-validate at send time (URL may have been stored under older rules / DNS changed)
            validate_callback_url(
                url,
                allow_http=self.settings.allow_http_callbacks,
                allow_private=self.settings.allow_private_callbacks,
                resolve=self.settings.ssrf_dns_check,
            )
        except UnsafeCallbackURL as exc:
            return CallbackResult(error=f"blocked: {exc}", blocked=True)
        try:
            with httpx.Client(timeout=self.settings.callback_timeout_seconds, follow_redirects=False) as client:
                resp = client.post(url, json=payload, headers={"User-Agent": "uidai-sandbox-risk/1.0"})
            return CallbackResult(status_code=resp.status_code)
        except httpx.HTTPError as exc:
            return CallbackResult(error=type(exc).__name__)  # class name only: no URL/body leakage
