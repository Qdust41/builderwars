# AWS setup checklist (owner's manual steps)

What the owner does by hand, in order, to get builderwars running in AWS. Nothing in this repo
deploys on its own; `docs/aws-deployment.md` has the deploy commands and the cost table, and this
page is the step-by-step around them.

Decisions this follows (don't re-decide them here): one environment, **prod**, in **us-east-1**
(open decisions #11/#12); RDS publicly reachable over TLS with Lambdas outside the VPC (ADR 0007,
in PR #7); Cognito self sign-up with email + password, MFA off (ADR 0005); Cognito's built-in
email sender for now (about 50 emails/day), SES later.

## 0. Merge first (blocks the deploy)

`main` today can synthesise prod but **cannot run it**: the Lambdas there have no bundled
dependencies, no PostgreSQL repositories and no AWS adapters. Deploy only after:

- [ ] **PR #5** (PostgreSQL repositories + migrations) is merged.
- [ ] **PR #7** (AWS adapters, Lambda bundling, public-RDS-over-TLS, `Migrate` Lambda) is
      retargeted to `main` and merged. It is stacked on #5.
- [ ] **PR #6** (web dashboard + web Cognito sign-in) is merged if you want the web app. It adds
      no AWS resources, so it does not block the backend deploy. After it merges, a small
      follow-up wires live device events into ingest and the command dispatcher.

Steps 1–4 below don't need any of these and can be done now.

## 1. AWS account (once, console)

- [ ] Create or pick the AWS account that will hold prod. New accounts (since July 2025) choose
      between a **Free plan** (credits, but the account is closed after its free period unless
      upgraded) and a **Paid plan** (same credits, keeps running). For an app that should stay
      up, pick Paid, or plan to upgrade. Check the current terms at
      <https://aws.amazon.com/free/>; the "12 months free" notes in `aws-deployment.md` assume
      the older free tier.
- [ ] Turn on **MFA for the root user**, then stop using root.
- [ ] **Billing → Budgets:** create a monthly cost budget (e.g. $10) with an email alert at 80%
      and 100%. This is the only spending alarm; the repo's alarms have no notification target
      yet (decision #13).
- [ ] Set the console region to **US East (N. Virginia) us-east-1** so you see the resources
      the deploy creates.

## 2. A deploy identity for your laptop (once)

CDK needs credentials with broad rights the first time (bootstrap creates IAM roles, and the
stacks create IAM roles, RDS, a VPC, IoT rules and so on).

- [ ] Recommended: **IAM Identity Center** → create a user for yourself → assign the
      `AdministratorAccess` permission set on this account → `aws configure sso` on your laptop
      (profile name e.g. `builderwars-prod`).
- [ ] Simpler alternative: an IAM user with `AdministratorAccess` and an access key, stored
      with `aws configure --profile builderwars-prod`. Never commit the key.
- [ ] Check it: `aws sts get-caller-identity --profile builderwars-prod` prints the account id.

## 3. Tools on the deploying machine

- [ ] AWS CLI v2.
- [ ] Node.js 22+ (for `npx aws-cdk@2`).
- [ ] Python 3.12 and **uv 0.11.32** (or Docker). After PR #7, `cdk synth/deploy` bundles the
      Lambda code from `uv.lock` and needs PyPI access.
- [ ] CDK app dependencies:
      `cd infrastructure && python -m venv .venv && .venv/bin/pip install -r requirements.txt`,
      then `source .venv/bin/activate` (`cdk.json` runs `python app.py` from your PATH).

## 4. Bootstrap CDK (once per account + region)

```bash
export AWS_PROFILE=builderwars-prod
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION=us-east-1
cd infrastructure
npx aws-cdk@2 bootstrap aws://$CDK_DEFAULT_ACCOUNT/us-east-1
```

- [ ] Done. This creates the `CDKToolkit` stack (an S3 asset bucket and ECR repo, both pennies).

## 5. Deploy prod (after step 0)

- [ ] `git pull` on `main`, then with the same variables as step 4:

```bash
npx aws-cdk@2 diff   -c env=prod --all
npx aws-cdk@2 deploy -c env=prod --all
```

- [ ] **Always pass `-c env=prod`.** `cdk.json` defaults to `dev`, which has no database, so the
      deployed API and workers refuse to start there.
- [ ] Read the IAM/security-change prompt before saying yes. Expected and deliberate: a
      security group allowing TCP 5432 from `0.0.0.0/0` (ADR 0007), Lambda roles reading the RDS
      secret, the IoT rule role, a custom resource that calls `iot:DescribeEndpoint`.
- [ ] The first deploy takes roughly 15–20 minutes, most of it the RDS instance.
- [ ] Save the outputs: `ApiUrl` (Api stack), `UserPoolId` and `UserPoolClientId` (Identity),
      `EventsHttpDns` and `EventsRealtimeDns` (Realtime), `DevicePolicyName` and
      `DataEndpointAddress` (Iot).

Stacks created (all prefixed `Builderwars-prod-`): Identity (Cognito), Storage (2 S3 buckets),
Messaging (SQS queues + DLQs), Iot (device policy, ingest rule), Realtime (AppSync Events),
Database (VPC with public subnets only, RDS PostgreSQL 16 `db.t4g.micro`, secret), Api (HTTP API
+ Lambda), Workers (ingest, command dispatch, jobs, Migrate Lambdas).

## 6. Run the database migrations (after every deploy that changes the schema)

The API and workers refuse to start until the schema is current, and nothing migrates by itself.

```bash
FN=$(aws lambda list-functions --region us-east-1 \
  --query "Functions[?contains(FunctionName, 'MigrateFunction')].FunctionName | [0]" --output text)
aws lambda invoke --region us-east-1 --function-name "$FN" /dev/stdout
```

- [ ] The response lists the applied migrations (`{"applied": [...]}`); an empty list later means
      nothing was pending.
- [ ] Smoke test: `curl <ApiUrl>/health` returns OK.

## 7. First account and sign-in

- [ ] Sign up through the web app (step 8) or create a user in the Cognito console (pool
      `builderwars-prod-users`), which emails a temporary password.
- [ ] Remember the ~50 emails/day cap from Cognito's built-in sender. Fine for a handful of
      people; move to SES before inviting more (see "Later").

## 8. Web app (after PR #6)

There is no hosting stack yet (S3 + CloudFront is the recommendation, still an open question).
Until then, run it locally against prod, which needs no CORS change because Vite proxies `/api`:

```bash
cd apps/web
VITE_API_PROXY_TARGET=<ApiUrl> \
VITE_AUTH_MODE=cognito \
VITE_COGNITO_USER_POOL_ID=<UserPoolId> VITE_COGNITO_CLIENT_ID=<UserPoolClientId> \
VITE_REALTIME_PROVIDER=appsync \
VITE_APPSYNC_EVENTS_HTTP_DNS=<EventsHttpDns> VITE_APPSYNC_EVENTS_REALTIME_DNS=<EventsRealtimeDns> \
npm run dev
```

## 9. Connecting a board (when the board work resumes)

Device registration in the API does not create IoT certificates yet (PR #4 is a draft), so for
now a board is provisioned by hand, as in `aws-deployment.md` → "Testing a real board":

- [ ] IoT console (or `aws iot create-thing`): create a thing named after the device id.
- [ ] Create a certificate for it, keep the files **outside the repo**, attach it to the thing and
      to the policy `builderwars-prod-device`.
- [ ] Point the host runtime at `DataEndpointAddress` with `DEVICE_TRANSPORT=mqtt` and the cert
      paths.

## Things that are not needed for the MVP

- **Domain / Route 53 / certificates:** not used. The API is on its `execute-api` URL and
  Cognito has no hosted-UI domain. Needed later for web hosting with your own domain.
- **SES:** not yet; Cognito's built-in sender is used.
- **Secrets you create by hand:** none. The RDS password is generated into Secrets Manager by
  the deploy; no API keys are required.
- **GitHub → AWS deploy credentials:** CI only synthesises; deploys are run by hand.

## Cost notes

Rough monthly figures at MVP volume (<10 boards); full table in `aws-deployment.md`.

| Item | While free tier/credits last | After |
| --- | --- | --- |
| RDS `db.t4g.micro` + 20 GB | covered | ~$12–15 |
| RDS public IPv4 address | ~$3.60 | ~$3.60 |
| Secrets Manager (1 secret) | ~$0.40 | ~$0.40 |
| CloudWatch alarms/logs | cents | cents |
| IoT Core, SQS, Lambda, API Gateway, S3, AppSync, Cognito | ~$0 at this volume | ~$0–2 |

The RDS instance runs (and bills) all the time, used or not. Prod keeps data on teardown:
`cdk destroy` leaves the RDS instance (deletion protection on), the S3 buckets and the Cognito
pool in place, so to stop all charges you delete those by hand afterwards.

## Later (before real users)

- Membership check on AppSync subscriptions (`stacks/realtime.py` TODO): until it exists, any
  signed-in user could subscribe to any project's channel.
- Move email to SES; restrict API CORS to the real web domain; host the web app.
- Revisit the public database endpoint (VPC endpoints, or IAM DB auth, which is already enabled).
- Alarm notifications (SNS) once there is a recipient (#13).
