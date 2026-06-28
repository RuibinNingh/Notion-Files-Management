"""Remote URL safety helpers for downloaded/probed user content."""
from __future__ import annotations

import ipaddress
import socket
import urllib.request
from urllib.parse import urlsplit

import requests


class UnsafeUrlError(ValueError):
    pass


def _is_blocked_host(hostname: str) -> bool:
    h = (hostname or "").strip().strip("[]").lower()
    if not h:
        return True
    if h == "localhost" or h.endswith(".localhost") or h.endswith(".local"):
        return True
    try:
        return not ipaddress.ip_address(h).is_global
    except ValueError:
        return False


def _resolve_host(hostname: str, port: int | None) -> set[str]:
    try:
        records = socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise UnsafeUrlError(f"URL hostname cannot be resolved: {hostname}") from e
    return {r[4][0] for r in records}


def assert_safe_remote_url(url: str) -> None:
    parts = urlsplit(str(url or "").strip())
    if parts.scheme not in ("http", "https"):
        raise UnsafeUrlError("Only http/https URLs are allowed")
    if parts.username or parts.password:
        raise UnsafeUrlError("URLs with embedded credentials are not allowed")
    if _is_blocked_host(parts.hostname or ""):
        raise UnsafeUrlError("Private, local, or reserved hosts are not allowed")
    for ip in _resolve_host(parts.hostname or "", parts.port):
        try:
            if not ipaddress.ip_address(ip).is_global:
                raise UnsafeUrlError("URL resolves to a private, local, or reserved address")
        except ValueError as e:
            raise UnsafeUrlError("URL resolves to an invalid address") from e


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        assert_safe_remote_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def safe_urlopen(req_or_url, *, timeout: float):
    url = req_or_url.full_url if isinstance(req_or_url, urllib.request.Request) else str(req_or_url)
    assert_safe_remote_url(url)
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    return opener.open(req_or_url, timeout=timeout)


def safe_urlretrieve(url: str, filename: str, reporthook=None, block_size: int = 8192) -> None:
    assert_safe_remote_url(url)
    with safe_urlopen(url, timeout=30) as resp:
        total = resp.headers.get("Content-Length")
        try:
            total_size = int(total) if total else -1
        except ValueError:
            total_size = -1
        count = 0
        if reporthook:
            reporthook(count, block_size, total_size)
        with open(filename, "wb") as out:
            while True:
                chunk = resp.read(block_size)
                if not chunk:
                    break
                out.write(chunk)
                count += 1
                if reporthook:
                    reporthook(count, block_size, total_size)


def safe_requests_head(url: str, **kwargs) -> requests.Response:
    assert_safe_remote_url(url)
    kwargs.setdefault("allow_redirects", False)
    return requests.head(url, **kwargs)


def safe_requests_get(url: str, **kwargs) -> requests.Response:
    assert_safe_remote_url(url)
    kwargs.setdefault("allow_redirects", False)
    return requests.get(url, **kwargs)
