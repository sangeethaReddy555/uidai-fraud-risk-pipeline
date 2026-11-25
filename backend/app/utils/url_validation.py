"""Callback URL validation / SSRF protection.

Blocks: non-HTTPS schemes, credentials in URL, localhost / metadata hostnames,
private / loopback / link-local / reserved / CGNAT IPs (v4 + v6, incl. IPv4-mapped),
obfuscated IP forms (decimal, octal, hex), and hostnames whose DNS answers include a
non-public address. Redirects are never followed by the sender.

Known limitation: DNS is re-resolved by the HTTP client at connect time, so a
DNS-rebinding attacker with a very low TTL can in theory still win the race. A production
deployment should additionally egress through a filtering proxy / network policy.
"""
import ipaddress
import re
import socket
from urllib.parse import urlsplit

BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "metadata.google.internal", "metadata"}
ALLOWED_PUBLIC_PORTS = {80, 443, 8080, 8443}
_NUMERIC_HOST = re.compile(r"^(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+))*$", re.I)


class UnsafeCallbackURL(ValueError):
    pass


def _check_ip(ip_str: str) -> None:
    ip = ipaddress.ip_address(ip_str)
    if ip.version == 6 and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if not ip.is_global:
        raise UnsafeCallbackURL("callback host resolves to a non-public address")


def _default_resolver(host: str, port: int) -> list[str]:
    return [info[4][0] for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]


def validate_callback_url(
    url: str,
    *,
    allow_http: bool = False,
    allow_private: bool = False,
    resolve: bool = True,
    resolver=_default_resolver,
) -> str:
    if not isinstance(url, str) or len(url) > 2048:
        raise UnsafeCallbackURL("callback URL missing or too long")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise UnsafeCallbackURL("callback URL is malformed") from None
    if parts.scheme not in ({"https", "http"} if allow_http else {"https"}):
        raise UnsafeCallbackURL("callback URL must use https")
    if parts.username or parts.password:
        raise UnsafeCallbackURL("credentials in callback URL are not allowed")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UnsafeCallbackURL("callback URL has no host")
    if allow_private:
        return url
    if host in BLOCKED_HOSTS or host.endswith((".localhost", ".internal", ".local")):
        raise UnsafeCallbackURL("callback host is not allowed")
    if port is not None and port not in ALLOWED_PUBLIC_PORTS:
        raise UnsafeCallbackURL("callback port is not allowed")

    try:
        ipaddress.ip_address(host)
        is_literal = True
    except ValueError:
        is_literal = False
    if is_literal:
        _check_ip(host)
        return url
    if _NUMERIC_HOST.match(host):  # 2130706433, 0x7f.1, 017700000001 ...
        raise UnsafeCallbackURL("obfuscated IP address in callback host")
    if resolve:
        try:
            addrs = resolver(host, port or (443 if parts.scheme == "https" else 80))
        except OSError:
            raise UnsafeCallbackURL("callback host cannot be resolved") from None
        if not addrs:
            raise UnsafeCallbackURL("callback host cannot be resolved")
        for addr in addrs:
            _check_ip(addr)
    return url
