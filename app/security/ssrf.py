"""URL validation (SSRF defence). The MVP never fetches; it only validates URLs before storing them.
Any future fetcher MUST call validate_url() first and re-validate every redirect hop (max 3)."""
import ipaddress
import socket
from typing import Callable, Optional
from urllib.parse import urlsplit


class UnsafeURL(ValueError):
    pass


def _default_resolver(host: str, port: int) -> list[str]:
    return [ai[4][0] for ai in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)]


def validate_url(url: str, allowed_domains: tuple, resolve: bool = True,
                 resolver: Optional[Callable[[str, int], list]] = None) -> str:
    parts = urlsplit(url.strip())
    if parts.scheme != "https":
        raise UnsafeURL("Only https URLs are allowed")
    if parts.username or parts.password:
        raise UnsafeURL("Credentials in URLs are not allowed")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UnsafeURL("Missing host")
    try:
        ipaddress.ip_address(host)
        raise UnsafeURL("IP-literal hosts are not allowed")
    except ValueError as e:
        if isinstance(e, UnsafeURL):
            raise
    if parts.port not in (None, 443):
        raise UnsafeURL("Non-standard ports are not allowed")
    if "*" not in allowed_domains and not any(host == d or host.endswith("." + d) for d in allowed_domains):
        raise UnsafeURL("Host is not on the official-source allowlist")
    if resolve:
        try:
            addrs = (resolver or _default_resolver)(host, 443)
        except OSError:
            raise UnsafeURL("Could not resolve host; unable to verify")
        if not addrs:
            raise UnsafeURL("Host did not resolve")
        for a in addrs:
            ip = ipaddress.ip_address(a)
            if getattr(ip, "ipv4_mapped", None):
                ip = ip.ipv4_mapped
            if not ip.is_global:  # loopback, private, link-local (169.254.169.254), reserved...
                raise UnsafeURL("Host resolves to a non-public address")
    return parts.geturl()
