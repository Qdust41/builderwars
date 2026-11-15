"""Auto-fix credentials in Secrets Manager and the auto-fix run queue (ADR 0012).

One secret per project, named ``{prefix}{project_id}`` (prefix ``builderwars/<env>/autofix/``),
holding ``{"llm_api_key": ..., "github_token": ...}``. Only the API writes it and only the
auto-fix worker reads it (infrastructure/stacks); the API never returns the values.
"""

from __future__ import annotations

import json
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


class SqsAutoFixQueue:
    def __init__(self, client: Any, queue_url: str) -> None:
        self._client = client
        self._queue_url = queue_url

    def enqueue_autofix(self, run_id: str) -> None:
        self._client.send_message(
            QueueUrl=self._queue_url, MessageBody=json.dumps({"run_id": run_id})
        )
