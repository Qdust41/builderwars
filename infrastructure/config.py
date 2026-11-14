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

    @property
    def removal_policy(self) -> RemovalPolicy:
        return RemovalPolicy.RETAIN if self.retain_data else RemovalPolicy.DESTROY

    def resource_name(self, suffix: str) -> str:
        return f"builderwars-{self.name}-{suffix}"


# RDS is off by default in dev to avoid its ongoing cost (see docs/aws-deployment.md); retention
# periods are placeholders until open decision #6 (volumes/retention) is settled.
ENVIRONMENTS: dict[str, EnvConfig] = {
    "dev": EnvConfig("dev", False, False, logs.RetentionDays.TWO_WEEKS, 30),
    "staging": EnvConfig("staging", True, True, logs.RetentionDays.ONE_MONTH, 90),
    "prod": EnvConfig("prod", True, True, logs.RetentionDays.THREE_MONTHS, 365),
}


def get_config(name: str) -> EnvConfig:
    try:
        return ENVIRONMENTS[name]
    except KeyError:
        raise ValueError(f"unknown env {name!r}; expected one of {sorted(ENVIRONMENTS)}") from None
