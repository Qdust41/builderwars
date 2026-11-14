"""PostgreSQL on RDS (``enable_rds``: prod only, decision #12). db.t4g.micro is free-tier
eligible for 12 months; after that it INCURS ONGOING COST.

Network (ADR 0006, owner decision 2026-11-14): the instance is PUBLICLY REACHABLE so that the
API and worker Lambdas can run outside a VPC and reach SQS, S3, IoT and AppSync without a NAT
gateway (~$32/month) or VPC endpoints (~$20-30/month). This reverses the scaffold's earlier
"no publicly accessible database" rule. What protects it instead:

* TLS is enforced by the server (``rds.force_ssl=1``) and requested by clients
  (``sslmode=require``).
* The admin password is generated into Secrets Manager; only the Lambdas' roles can read it.
* Storage is encrypted, backups kept 7 days, deletion protection on in prod.

Lambda has no fixed source IPs, so the security group cannot narrow by address; it allows
PostgreSQL (5432) from anywhere and nothing else. Revisit (VPC + endpoints) before real users.
"""

from __future__ import annotations

from typing import Any

from aws_cdk import Acknowledgment, Duration, Stack, Validations
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_rds as rds
from aws_cdk import aws_secretsmanager as secretsmanager
from config import EnvConfig
from constructs import Construct

ENGINE = rds.DatabaseInstanceEngine.postgres(version=rds.PostgresEngineVersion.VER_16)


class DatabaseStack(Stack):
    def __init__(self, scope: Construct, cid: str, *, config: EnvConfig, **kw: Any) -> None:
        super().__init__(scope, cid, **kw)
        # Public subnets only: an internet gateway is free; no NAT gateways.
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                )
            ],
        )
        self.security_group = ec2.SecurityGroup(
            self,
            "PostgresAccess",
            vpc=self.vpc,
            description="PostgreSQL over TLS from Lambda (no fixed source IPs; ADR 0006)",
            allow_all_outbound=False,
        )
        self.security_group.add_ingress_rule(
            ec2.Peer.any_ipv4(), ec2.Port.tcp(5432), "PostgreSQL (TLS enforced by the server)"
        )
        parameters = rds.ParameterGroup(
            self,
            "Parameters",
            engine=ENGINE,
            description="builderwars: TLS only",
            parameters={"rds.force_ssl": "1"},
        )
        self.instance = rds.DatabaseInstance(
            self,
            "Postgres",
            engine=ENGINE,
            instance_type=ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO),
            vpc=self.vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_groups=[self.security_group],
            publicly_accessible=True,  # ADR 0006
            parameter_group=parameters,
            storage_encrypted=True,
            allocated_storage=20,  # free tier: 20 GB; no storage autoscaling (decision #11)
            credentials=rds.Credentials.from_generated_secret("builderwars_admin"),
            database_name="builderwars",
            backup_retention=Duration.days(7),
            deletion_protection=config.retain_data,
            removal_policy=config.removal_policy,
            iam_authentication=True,
        )
        # Both are deliberate (ADR 0006); acknowledged so synth reports stay readable.
        Validations.of(self).acknowledge(
            Acknowledgment(
                id="CloudFormation-Validate::W2508",
                reason="Lambda has no fixed source IPs; TLS is enforced (ADR 0006)",
            ),
            Acknowledgment(
                id="CloudFormation-Validate::W9011",
                reason="Publicly reachable over TLS by owner decision (ADR 0006)",
            ),
        )
        assert self.instance.secret is not None  # from_generated_secret always creates one
        self.secret: secretsmanager.ISecret = self.instance.secret
