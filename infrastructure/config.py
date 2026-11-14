"""Per-environment settings. Nothing here is a secret or an account id.

Select with ``-c env=dev|staging|prod``. Account/region come from the standard
``CDK_DEFAULT_ACCOUNT`` / ``CDK_DEFAULT_REGION`` variables at deploy time (never hard-coded).
"""

from __future__ import annotations

from dataclasses import dataclass

from aws_cdk import RemovalPolicy
from aws_cdk import aws_logs as logs


@dataclass(frozen=True)
class EnvConfig:
    name: str
    enable_rds: bool
    retain_data: bool
    log_retention: logs.RetentionDays
    raw_data_expiry_days: int
    # Placeholder only: alarm actions are out of MVP scope (decision #13). Not wired to SNS.
    ops_alert_email: str = "ops-alerts@example.com"

    @property
    def removal_policy(self) -> RemovalPolicy:
        return RemovalPolicy.RETAIN if self.retain_data else RemovalPolicy.DESTROY

    def resource_name(self, suffix: str) -> str:
        return f"builderwars-{self.name}-{suffix}"


# Decisions #11/#12: us-east-1 (via CDK_DEFAULT_REGION), free tier. RDS (db.t4g.micro) in prod
# only. Raw-data retention 30/90/365 days (decision #6).
ENVIRONMENTS: dict[str, EnvConfig] = {
    "dev": EnvConfig("dev", False, False, logs.RetentionDays.TWO_WEEKS, 30),
    "staging": EnvConfig("staging", False, True, logs.RetentionDays.ONE_MONTH, 90),
    "prod": EnvConfig("prod", True, True, logs.RetentionDays.THREE_MONTHS, 365),
}


def get_config(name: str) -> EnvConfig:
    try:
        return ENVIRONMENTS[name]
    except KeyError:
        raise ValueError(f"unknown env {name!r}; expected one of {sorted(ENVIRONMENTS)}") from None
