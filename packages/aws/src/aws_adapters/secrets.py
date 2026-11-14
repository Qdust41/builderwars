"""Turn the RDS-generated Secrets Manager secret into a ``DATABASE_URL``.

The secret RDS generates is JSON with ``username``, ``password``, ``host``, ``port`` and
``dbname``. The URL always asks for TLS (``sslmode=require``); the prod database enforces it
too (``rds.force_ssl``, ADR 0007).
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote


def database_url_from_secret(client: Any, secret_id: str, *, sslmode: str = "require") -> str:
    response = client.get_secret_value(SecretId=secret_id)
    secret = json.loads(response["SecretString"])
    user = quote(str(secret["username"]), safe="")
    password = quote(str(secret["password"]), safe="")
    host = secret["host"]
    port = int(secret.get("port", 5432))
    dbname = quote(str(secret.get("dbname", "builderwars")), safe="")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}?sslmode={sslmode}"
