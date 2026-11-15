# Infrastructure (AWS CDK, Python)

Defines every AWS resource. One deployed environment, **prod** in us-east-1, with no staging;
`dev` exists for synth checks and personal sandboxes only (it has no database). Settings per
environment are in `config.py`.

**Merging to `main` deploys prod** (`.github/workflows/deploy.yml`): after CI passes it deploys
every stack, runs the Migrate Lambda and checks `/health`. Pull requests never deploy. The full
walkthrough, including the first deploy by hand, OIDC and DNS, is
[docs/deployment-guide.md](../docs/deployment-guide.md).

## Synth and test (no AWS calls)

CDK has its own virtualenv; it is not part of the uv workspace.

```bash
cd infrastructure
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python app.py                                  # synth dev -> cdk.out/
CDK_CONTEXT_JSON='{"env":"prod"}' .venv/bin/python app.py # synth prod
.venv/bin/python -m pytest tests                         # synth assertions
# or: npx aws-cdk@2 synth -c env=prod
```

Synth bundles the Lambda code from `uv.lock` for arm64 (`lambda_bundle.py`), so it needs `uv`
on `PATH` (or Docker) and access to PyPI.

## Deploy by hand

```bash
export AWS_PROFILE=builderwars-prod AWS_REGION=us-east-1 CDK_DEFAULT_REGION=us-east-1
AWS_REGION=us-east-1 ../scripts/build_web_prod.sh        # build the web app, or its upload is skipped
npx aws-cdk@2 diff   -c env=prod --all
npx aws-cdk@2 deploy -c env=prod --all
```

Always pass `-c env=prod`; `cdk.json` defaults to `dev`. Then run the Migrate Lambda (step 7 of
the deployment guide).

## Stacks (`stacks/`, named `Builderwars-<env>-…`)

| Stack | Module | What's in it |
| --- | --- | --- |
| Identity | `identity.py` | Cognito user pool + app client (self sign-up, email + password) |
| Storage | `storage.py` | device-data and artifacts S3 buckets |
| Messaging | `messaging.py` | ingest, jobs and commands SQS queues + DLQs |
| Iot | `iot.py` | device policy, ingest rule `devices/+/+` → SQS |
| Realtime | `realtime.py` | AppSync Events API (subscribe membership check: TODO) |
| Database | `database.py` | VPC (public subnets), RDS PostgreSQL 16, publicly reachable over TLS (ADR 0007) |
| Api | `api.py` | HTTP API + API Lambda |
| Workers | `workers.py` | DeviceIngest, CommandDispatch, Jobs, Migrate Lambdas |
| Web | `web.py` | S3 + CloudFront for the web app, `/api/*` → the HTTP API, ACM certificate |

`packaging.py` and `lambda_bundle.py` build the Lambda assets.
