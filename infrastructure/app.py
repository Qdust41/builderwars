#!/usr/bin/env python3
"""CDK app. SYNTH ONLY from this repo's tooling — nothing here deploys.

    cd infrastructure && python app.py                  # writes cdk.out/ (no AWS calls)
    cd infrastructure && npx aws-cdk@2 synth -c env=dev  # same, via the CDK CLI

Deployment is a deliberate, manual step (docs/aws-deployment.md).
"""

from __future__ import annotations

import os

import aws_cdk as cdk
from config import EnvConfig, get_config

from stacks.api import ApiStack
from stacks.database import DatabaseStack
from stacks.identity import IdentityStack
from stacks.iot import IotStack
from stacks.messaging import MessagingStack
from stacks.realtime import RealtimeStack
from stacks.storage import StorageStack
from stacks.workers import WorkersStack


def build(app: cdk.App, config: EnvConfig) -> dict[str, cdk.Stack]:
    account = os.environ.get("CDK_DEFAULT_ACCOUNT")
    region = os.environ.get("CDK_DEFAULT_REGION")
    env = cdk.Environment(account=account, region=region) if account and region else None
    prefix = f"Builderwars-{config.name}"

    identity = IdentityStack(app, f"{prefix}-Identity", config=config, env=env)
    storage = StorageStack(app, f"{prefix}-Storage", config=config, env=env)
    messaging = MessagingStack(app, f"{prefix}-Messaging", config=config, env=env)
    iot = IotStack(
        app, f"{prefix}-Iot", config=config, ingest_queue=messaging.ingest_queue, env=env
    )
    realtime = RealtimeStack(
        app, f"{prefix}-Realtime", config=config, user_pool=identity.user_pool, env=env
    )
    api = ApiStack(
        app,
        f"{prefix}-Api",
        config=config,
        user_pool=identity.user_pool,
        user_pool_client=identity.user_pool_client,
        jobs_queue=messaging.jobs_queue,
        artifacts_bucket=storage.artifacts_bucket,
        env=env,
    )
    workers = WorkersStack(
        app,
        f"{prefix}-Workers",
        config=config,
        ingest_queue=messaging.ingest_queue,
        jobs_queue=messaging.jobs_queue,
        device_data_bucket=storage.device_data_bucket,
        artifacts_bucket=storage.artifacts_bucket,
        env=env,
    )
    stacks: dict[str, cdk.Stack] = {
        "identity": identity,
        "storage": storage,
        "messaging": messaging,
        "iot": iot,
        "realtime": realtime,
        "api": api,
        "workers": workers,
    }
    if config.enable_rds:
        stacks["database"] = DatabaseStack(app, f"{prefix}-Database", config=config, env=env)
    for stack in stacks.values():
        cdk.Tags.of(stack).add("project", "builderwars")
        cdk.Tags.of(stack).add("environment", config.name)
    return stacks


def main() -> None:
    app = cdk.App(outdir=os.environ.get("CDK_OUTDIR", "cdk.out"))
    build(app, get_config(app.node.try_get_context("env") or "dev"))
    app.synth()


if __name__ == "__main__":
    main()
