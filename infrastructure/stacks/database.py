"""PostgreSQL on RDS (``enable_rds``: prod only, decision #12). db.t4g.micro is free-tier
eligible for 12 months; after that it INCURS ONGOING COST.

Private subnets only, encrypted, credentials generated into Secrets Manager. No NAT gateways
(cost); Lambdas that need the DB will need VPC endpoints for other AWS services. When RDS is
disabled (dev default), the application has no persistent store yet — see
docs/decisions/0003-local-adapters.md. We do not substitute a different production data model.
"""

from __future__ import annotations

from typing import Any

from aws_cdk import Duration, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from config import EnvConfig
from constructs import Construct


class DatabaseStack(Stack):
    def __init__(self, scope: Construct, cid: str, *, config: EnvConfig, **kw: Any) -> None:
        super().__init__(scope, cid, **kw)
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="isolated", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24
                )
            ],
        )
        self.instance = rds.DatabaseInstance(
            self,
            "Postgres",
            engine=rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_16),
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            publicly_accessible=False,
            storage_encrypted=True,
            allocated_storage=20,  # free tier: 20 GB; no storage autoscaling (decision #11)
            credentials=rds.Credentials.from_generated_secret("builderwars_admin"),
            database_name="builderwars",
            backup_retention=Duration.days(7),
            deletion_protection=config.retain_data,
            removal_policy=config.removal_policy,
            iam_authentication=True,
        )
