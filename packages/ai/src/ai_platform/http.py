"""Minimal JSON-over-HTTPS for the LLM endpoint and GitHub (standard library only, so the
Lambda bundle gains no dependency). Tests swap ``HttpTransport`` for a fake."""

from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import urlsplit


class HttpError(RuntimeError):
    """A request failed. ``str()`` is safe to store and show: it never includes headers."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: bytes

    def json(self) -> Any:
        try:
            return json.loads(self.body or b"null")
        except ValueError as exc:
            raise HttpError(f"expected JSON, got {self.body[:120]!r}", status=self.status) from exc


class HttpTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse: ...


class UrllibTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
    ) -> HttpResponse:
        if urlsplit(url).scheme not in {"http", "https"}:
            raise HttpError(f"refusing non-http URL {url!r}")
        request = urllib.request.Request(url, data=body, headers=headers, method=method)  # noqa: S310
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return HttpResponse(response.status, response.read())
        except urllib.error.HTTPError as exc:
            return HttpResponse(exc.code, exc.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise HttpError(f"could not reach {urlsplit(url).netloc}: {reason}") from exc


def send_json(
    transport: HttpTransport,
    method: str,
    url: str,
    *,
    headers: dict[str, str],
    payload: Any = None,
    timeout: float = 30.0,
) -> HttpResponse:
    body = None if payload is None else json.dumps(payload).encode()
    all_headers = {"Accept": "application/json", **headers}
    if body is not None:
        all_headers["Content-Type"] = "application/json"
    return transport.request(method, url, headers=all_headers, body=body, timeout=timeout)


def ensure_public_endpoint(url: str) -> None:
    """Refuse endpoints that resolve to loopback, private, link-local or reserved addresses.

    The worker runs in AWS with the project admin choosing the URL, so this keeps a base URL
    from reaching the Lambda runtime API or anything else that is not a public LLM service.
    Local development skips this check (a local Ollama is on localhost).
    """
    parts = urlsplit(url)
    host = parts.hostname
    if not host:
        raise HttpError(f"no host in {url!r}")
    try:
        infos = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except OSError as exc:
        raise HttpError(f"could not resolve {host}: {exc}") from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise HttpError(f"{host} resolves to a non-public address; use a public endpoint")
