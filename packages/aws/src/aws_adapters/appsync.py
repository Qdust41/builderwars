"""``RealtimePublisher`` over the AppSync Events HTTP publish API.

``POST https://{http_dns}/event`` with ``{"channel": "/projects/...", "events": ["<json>"]}``,
signed with SigV4 (service ``appsync``); the Events API only accepts IAM for publishing, so
browsers can subscribe but never publish (infrastructure/stacks/realtime.py).
"""

from __future__ import annotations

import json
import logging
import urllib.request
from collections.abc import Callable
from typing import Any

from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

from application.realtime import RealtimeEvent

log = logging.getLogger(__name__)

# (url, body, headers, timeout) -> (status, response body)
Sender = Callable[[str, bytes, dict[str, str], float], tuple[int, bytes]]


class RealtimePublishError(RuntimeError):
    pass


def urllib_send(
    url: str, body: bytes, headers: dict[str, str], timeout: float
) -> tuple[int, bytes]:
    if not url.startswith("https://"):
        raise ValueError("AppSync publish URL must be https")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            return int(response.status), bytes(response.read())
    except urllib.error.HTTPError as exc:
        return int(exc.code), bytes(exc.read())


class AppSyncEventsPublisher:
    def __init__(
        self,
        *,
        http_dns: str,
        region: str,
        credentials: Callable[[], Any],
        send: Sender = urllib_send,
        timeout: float = 5.0,
    ) -> None:
        """``credentials`` returns botocore credentials, e.g. ``boto3.Session().get_credentials``
        (called per publish, so refreshed Lambda credentials are picked up)."""
        self._url = f"https://{http_dns}/event"
        self._host = http_dns
        self._region = region
        self._credentials = credentials
        self._send = send
        self._timeout = timeout

    def publish(self, event: RealtimeEvent) -> None:
        body = json.dumps(
            {"channel": f"/{event.channel}", "events": [event.model_dump_json()]}
        ).encode()
        request = AWSRequest(
            method="POST",
            url=self._url,
            data=body,
            headers={"content-type": "application/json", "host": self._host},
        )
        SigV4Auth(self._credentials(), "appsync", self._region).add_auth(request)
        status, response = self._send(
            self._url, body, {k: str(v) for k, v in request.headers.items()}, self._timeout
        )
        if status != 200:
            raise RealtimePublishError(f"AppSync publish failed with HTTP {status}")
        failed = json.loads(response or b"{}").get("failed") or []
        if failed:
            raise RealtimePublishError(f"AppSync rejected {len(failed)} event(s): {failed}")
