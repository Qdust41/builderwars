"""Auto-fix credentials in Secrets Manager and the auto-fix run queue (ADR 0012).

One secret per project, named ``{prefix}{project_id}`` (prefix ``builderwars/<env>/autofix/``),
holding ``{"llm_api_key": ..., "github_token": ...}``; both optional, since the GitHub token
usually comes from the one app-wide secret (``shared_autofix_secrets``). Only the API writes
project secrets and only the auto-fix worker reads them (infrastructure/stacks); the API never
returns the values.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from botocore.exceptions import ClientError

from application.ports import AutoFixSecrets


def _code(exc: ClientError) -> str:
    return str(exc.response.get("Error", {}).get("Code", ""))


class SecretsManagerAutoFixSecretStore:
    def __init__(self, client: Any, prefix: str) -> None:
        self._client = client
        self._prefix = prefix

    def name(self, project_id: str) -> str:
        return f"{self._prefix}{project_id}"

    def get(self, project_id: str) -> AutoFixSecrets:
        try:
            response = self._client.get_secret_value(SecretId=self.name(project_id))
        except ClientError as exc:
            if _code(exc) in {"ResourceNotFoundException", "InvalidRequestException"}:
                return AutoFixSecrets()  # never set, or deleted
            raise
        data = json.loads(response.get("SecretString") or "{}")
        return AutoFixSecrets(
            llm_api_key=data.get("llm_api_key") or None,
            github_token=data.get("github_token") or None,
        )

    def put(self, project_id: str, secrets: AutoFixSecrets) -> None:
        name = self.name(project_id)
        value = json.dumps(
            {"llm_api_key": secrets.llm_api_key, "github_token": secrets.github_token}
        )
        try:
            self._client.put_secret_value(SecretId=name, SecretString=value)
            return
        except ClientError as exc:
            if _code(exc) != "ResourceNotFoundException":
                raise
        self._client.create_secret(
            Name=name,
            SecretString=value,
            Description="builderwars auto-fix: LLM API key and GitHub token for one project",
            Tags=[{"Key": "project_id", "Value": project_id}],
        )

    def delete(self, project_id: str) -> None:
        try:
            self._client.delete_secret(
                SecretId=self.name(project_id), ForceDeleteWithoutRecovery=True
            )
        except ClientError as exc:
            if _code(exc) != "ResourceNotFoundException":
                raise


def shared_autofix_secrets(client: Any, secret_id: str) -> Callable[[], AutoFixSecrets]:
    """The app-wide credentials: one secret, ``{"github_token": ...}``, created by the Workers
    stack and filled at deploy time from the ``AUTOFIX_GITHUB_TOKEN`` GitHub Actions secret.
    Read on every run, so a rotated token is picked up without a redeploy of the code."""

    def load() -> AutoFixSecrets:
        response = client.get_secret_value(SecretId=secret_id)
        data = json.loads(response.get("SecretString") or "{}")
        return AutoFixSecrets(
            llm_api_key=data.get("llm_api_key") or None,
            github_token=data.get("github_token") or None,
        )

    return load


class SqsAutoFixQueue:
    def __init__(self, client: Any, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    def enqueue_autofix(self, run_id: str) -> None:
        self._client.send_message(
            QueueUrl=self._queue_url, MessageBody=json.dumps({"run_id": run_id})
        )
