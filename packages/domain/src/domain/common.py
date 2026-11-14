from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4


def new_id(prefix: str) -> str:
    """Opaque, prefixed identifiers (e.g. ``prj_3f2a...``) that are safe in URLs and topics."""
    return f"{prefix}_{uuid4().hex}"


def utcnow() -> datetime:
    return datetime.now(UTC)


class DomainError(Exception):
    """Base class for domain/application errors that the API maps to HTTP responses."""


class NotFoundError(DomainError):
    def __init__(self, kind: str, identifier: str) -> None:
        super().__init__(f"{kind} {identifier!r} not found")
        self.kind = kind
        self.identifier = identifier


class PermissionDeniedError(DomainError):
    pass


class InvalidStateTransitionError(DomainError):
    pass


class ConflictError(DomainError):
    """The request conflicts with current state (e.g. the user is already a member)."""
