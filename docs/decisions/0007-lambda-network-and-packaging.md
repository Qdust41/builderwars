# 0006 — Lambdas outside the VPC, public RDS over TLS; bundled Lambda assets

Status: accepted (2026-11-14, workstream C; network choice made by the owner)

## Context
The API and worker Lambdas need PostgreSQL (RDS, prod only) and also SQS, S3, IoT Core,
AppSync Events and Secrets Manager. A Lambda inside a VPC with no internet route reaches none of
those services without paid networking. Options put to the owner:

| Option | Cost | Database exposure |
| --- | --- | --- |
| NAT gateway | ~$32/month | private |
| VPC endpoints (SQS, S3, IoT, AppSync, Secrets Manager) | ~$20–30/month | private |
| Lambdas outside the VPC, RDS publicly reachable over TLS | ~$0 | public endpoint |

## Decision
- **Network (owner's choice):** the Lambdas run outside any VPC. The RDS instance sits in a
  public subnet with `PubliclyAccessible: true`. **This reverses the scaffold's rule that no
  database is publicly accessible** (previous `database.py`: private isolated subnets).
- **What protects the database instead:** the server enforces TLS (`rds.force_ssl=1`) and
  clients ask for it (`sslmode=require`); the admin password is generated into Secrets Manager
  and only the API/worker roles can read it (`DATABASE_SECRET_ARN`, resolved into
  `DATABASE_URL` at cold start, never in plain environment variables); storage encrypted,
  7-day backups, deletion protection. Lambda has no fixed source IPs, so the security group
  allows TCP 5432 from any IPv4 address and nothing else.
- **Connections:** each container holds one (workers) or up to two (API) connections; each
  SQS event source is capped at 2 concurrent invocations.
- **Migrations:** a `Migrate` Lambda (`workers.main.migrate_lambda_handler`) applies pending
  migrations when invoked by hand after a deploy. Services never migrate on their own (ADR 0005).
- **Packaging:** Lambda assets are bundled at synth time by `infrastructure/lambda_bundle.py`:
  `uv export --frozen` (versions from `uv.lock`) installed for Python 3.12 /
  `aarch64-manylinux_2_28`, plus the source of each workspace package the app uses. CDK runs it
  locally when `uv` is on PATH, otherwise in the Lambda Python build image through Docker.
- **IoT data endpoint:** looked up at deploy time with a CDK `AwsCustomResource`
  (`iot:DescribeEndpoint`, `iot:Data-ATS`) and passed as `IOT_DATA_ENDPOINT`.
- **Raw messages:** the ingest worker writes raw bodies to S3 `raw/` and rejected ones to
  `rejected/` (both expire with the raw-data retention) instead of the PostgreSQL raw tables,
  which stay for local runs.

## Consequences
- ~$0/month extra networking. The database's endpoint is reachable from the internet;
  brute force is the main risk, mitigated only by the generated password and TLS.
- Revisit before real users: move to VPC endpoints (Lambdas in private subnets, RDS private),
  or switch to IAM database authentication (already enabled on the instance) so no password
  exists at all.
- `cdk synth` now needs `uv` (or Docker) and PyPI access; CI installs uv for the infra job.
  Template tests skip bundling (`aws:cdk:bundling-stacks: []`).
