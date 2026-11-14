"""S3 buckets: private, encrypted, TLS-only, with lifecycle defaults."""

from __future__ import annotations

from typing import Any

from aws_cdk import Duration, Stack
from aws_cdk import aws_s3 as s3
from config import EnvConfig
from constructs import Construct


class StorageStack(Stack):
    def __init__(self, scope: Construct, cid: str, *, config: EnvConfig, **kw: Any) -> None:
        super().__init__(scope, cid, **kw)
        common: dict[str, Any] = {
            "block_public_access": s3.BlockPublicAccess.BLOCK_ALL,
            "encryption": s3.BucketEncryption.S3_MANAGED,  # TODO: KMS CMK if compliance needs it
            "enforce_ssl": True,
            "object_ownership": s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
            "removal_policy": config.removal_policy,
            "auto_delete_objects": not config.retain_data,
        }
        # Firmware/build artifacts are immutable references -> versioned, never auto-expired.
        self.artifacts_bucket = s3.Bucket(
            self,
            "Artifacts",
            versioned=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    noncurrent_version_expiration=Duration.days(90),
                    abort_incomplete_multipart_upload_after=Duration.days(7),
                )
            ],
            **common,
        )
        # Raw device messages and exports. Retention is provisional (open decision #6).
        self.device_data_bucket = s3.Bucket(
            self,
            "DeviceData",
            lifecycle_rules=[
                s3.LifecycleRule(
                    prefix="raw/",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=Duration.days(30),
                        )
                    ]
                    if config.raw_data_expiry_days > 30
                    else [],
                    expiration=Duration.days(config.raw_data_expiry_days),
                ),
                s3.LifecycleRule(abort_incomplete_multipart_upload_after=Duration.days(7)),
            ],
            **common,
        )
