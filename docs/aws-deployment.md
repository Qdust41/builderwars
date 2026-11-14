# AWS deployment (future — not performed by the scaffold)

Nothing in this repository deploys automatically. CI only synthesises templates.

## Before the first deploy

1. Region (us-east-1), budget (free tier) and volumes are decided (#6, #11). Still open:
   staging storage (#12) and alarm recipients (#13, out of MVP scope).
2. Implement the TODOs that make the deployed API start: Cognito auth mode, PostgreSQL
   repositories (or decide on another store via an ADR), SQS/AppSync/IoT adapters.
3. Bundle Lambda dependencies (`uv export --package bw-api` → `pip install --target`, or switch
   to container images built from `docker/`).
4. Add alarm actions (SNS topic) and restrict CORS.

## Deploying (manual, deliberate)

```bash
export AWS_PROFILE=<your-dev-profile>
export CDK_DEFAULT_ACCOUNT=<account-id> CDK_DEFAULT_REGION=us-east-1
cd infrastructure
npx aws-cdk@2 bootstrap                 # once per account/region
npx aws-cdk@2 diff -c env=dev
npx aws-cdk@2 deploy -c env=dev --all   # review the IAM/security-change prompt carefully
```

## Resources with ongoing cost

| Resource | Notes |
| --- | --- |
| RDS PostgreSQL (prod only) | `db.t4g.micro`, 20 GB: free tier for 12 months (750 h/mo), then hourly. |
| AWS IoT Core | ~518k messages/month at 10 devices × 1 msg/5 s, inside the 1M free tier. Connection minutes and rule actions also count. |
| AppSync Events | Per connection-minute and per event. |
| SQS, Lambda, API Gateway | Per request; near zero at idle. |
| S3 | Storage + requests; lifecycle rules limit raw data growth. |
| CloudWatch | Log ingestion/storage (retention set per env), alarms per month. |
| Secrets Manager | Per secret per month (RDS credentials). |
| Cognito | Free tier, then per MAU. |

## Testing a real board / simulator against a dev IoT endpoint

The local simulator prints JSON lines and is **not** an authenticated IoT device. To test the
real path once `MqttTransport` is implemented:

1. Deploy the `Iot`, `Messaging` and `Workers` stacks to a dev account.
2. Create a thing named after the device id (e.g. `dev-bench-001`); create a certificate for it
   *outside* the repo (console or `aws iot create-keys-and-certificate`), store the files outside
   the repo, attach the certificate to the thing and to the `builderwars-dev-device` policy.
3. Find the endpoint: `aws iot describe-endpoint --endpoint-type iot:Data-ATS`.
4. Run the runtime with `DEVICE_TRANSPORT=mqtt`, `IOT_ENDPOINT`, `IOT_CERT_PATH`, `IOT_KEY_PATH`,
   `IOT_CA_PATH` set (see `.env.example`).
5. Watch the MQTT test client in the IoT console, the ingest queue/DLQ, and worker logs.
6. Delete the test certificate when finished.
