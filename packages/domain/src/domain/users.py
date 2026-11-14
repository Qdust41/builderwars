from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class User:
    """A human account as the identity provider (Cognito) knows it.

    ``user_id`` is the provider's stable subject (Cognito ``sub``); email can change.
    """

    user_id: str
    email: str


def normalize_email(email: str) -> str:
    return email.strip().lower()
