"""Per-environment settings. Nothing here is a secret or an account id.

Select with ``-c env=dev|prod``. There is no staging environment for the MVP (decision #12):
changes go local -> prod. ``dev`` is for synth checks and personal sandboxes only; it has no
database, so the deployed API refuses to start there until a persistent store exists.
Account/region come from the standard ``CDK_DEFAULT_ACCOUNT`` / ``CDK_DEFAULT_REGION``
variables at deploy time (never hard-coded).
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
    # Public hostname of the web app (DNS lives in Cloudflare, see docs/deployment-guide.md).
    # None serves the app on the CloudFront domain only, with no certificate.
    web_domain: str | None = None

    @property
    def removal_policy(self) -> RemovalPolicy:
        return RemovalPolicy.RETAIN if self.retain_data else RemovalPolicy.DESTROY

    def resource_name(self, suffix: str) -> str:
        return f"builderwars-{self.name}-{suffix}"

    @property
    def autofix_secret_prefix(self) -> str:
        """Secrets Manager names of each project's auto-fix keys: ``<prefix><project_id>``."""
        return f"builderwars/{self.name}/autofix/"

    @property
    def autofix_shared_secret_name(self) -> str:
        """The one GitHub token for every project. Outside ``autofix_secret_prefix``, so the
        API (which may write project secrets) cannot read or change it."""
        return f"builderwars/{self.name}/autofix-shared"


# Decisions #11/#12: us-east-1 (via CDK_DEFAULT_REGION), free tier. RDS (db.t4g.micro) in prod
# only; no staging. Raw-data retention 30 (dev) / 365 (prod) days (decision #6).
ENVIRONMENTS: dict[str, EnvConfig] = {
    "dev": EnvConfig("dev", False, False, logs.RetentionDays.TWO_WEEKS, 30),
    "prod": EnvConfig(
        "prod",
        True,
        True,
        logs.RetentionDays.THREE_MONTHS,
        365,
        web_domain="builderwars.jimweaver.com",
    ),
}


def get_config(name: str) -> EnvConfig:
    try:
        return ENVIRONMENTS[name]
    except KeyError:
        raise ValueError(f"unknown env {name!r}; expected one of {sorted(ENVIRONMENTS)}") from None
