# Deployment guide (prod, end to end)

Everything the owner does by hand to go from an empty AWS account to a FREE-WILi board sending
data that shows up in the web dashboard. The first deploy is by hand; after that, merging to
`main` deploys prod through GitHub Actions (see "Deploying from GitHub Actions"). `docs/aws-deployment.md` keeps the short command list and the cost table;
this page is the full walkthrough around it.

Decisions this follows (don't re-decide them here):

- One deployed environment, **prod**, in **us-east-1**. No staging: local -> prod (#11, #12).
- RDS PostgreSQL is **publicly reachable over TLS**; Lambdas run **outside the VPC**, so there is
  no NAT gateway or VPC endpoints (ADR 0007, PR #7).
- Cognito: **self sign-up on, email + password, MFA off**, Cognito's built-in email sender
  (about 50 emails/day). No SES and no custom domain yet (ADR 0005).
- A "device" is a **host PC wired over USB to a FREE-WILi**; the host runtime is Python 3.10+
  (ADR 0004). Boards have **no IoT certificates** for now: the user signs in to the
  `builderwars` CLI and it uploads through the API as them (ADR 0009). The MQTT/certificate path
  (steps 11 and the end of 13) is parked.

## The whole path at a glance

| # | Step | Where | Notes |
| --- | --- | --- | --- |
| 1 | AWS account, root MFA, budget alert | AWS console | once |
| 2 | Deploy identity for your laptop | AWS console + laptop | once |
| 3 | Tools on the deploying laptop | laptop | |
| 4 | Get the code and check it | laptop | |
| 5 | `cdk bootstrap` | laptop | once per account + region |
| 6 | `cdk deploy -c env=prod --all` | laptop or GitHub Actions | merges to `main` do this |
| 7 | Run the Migrate Lambda, smoke test | laptop or GitHub Actions | merges to `main` do this |
| 8 | Open the web dashboard | browser | <https://builderwars.jimweaver.com> |
| 9 | Sign up, create a project | browser | |
| 10 | Register a device, note its id | browser | |
| 11 | Give the device an IoT identity (thing + certificate) | laptop | **skip for now** (ADR 0009) |
| 12 | Set up the host PC and test the board | host PC | the `builderwars` CLI |
| 13 | Connect the board: `builderwars login`, `run --cloud` | host PC | steps 10 and 12 |
| 14 | Verify end to end | browser | step 13 |

Everything prod needs is on `main`; there are no PRs to wait for. After the first deploy by
hand (steps 1-7), **every merge to `main` deploys prod** (see "Deploying from GitHub Actions"),
so most people only need steps 9-14.

## 1. AWS account (once, console)

- [ ] Create or pick the AWS account that will hold prod. New accounts (since July 2025) choose
      between a **Free plan** (credits, but the account is closed after its free period unless
      upgraded) and a **Paid plan** (same credits, keeps running). For an app that should stay
      up, pick Paid or plan to upgrade. Check the current terms at
      <https://aws.amazon.com/free/>; the "12 months free" notes in `aws-deployment.md` assume
      the older free tier.
- [ ] Turn on **MFA for the root user**, then stop using root.
- [ ] **Billing → Budgets:** a monthly cost budget (e.g. $10) with email alerts at 80% and 100%.
      This is the only spending alarm; the repo's alarms have no notification target yet (#13).
- [ ] Set the console region to **US East (N. Virginia) us-east-1** so you see what the deploy
      creates.

## 2. A deploy identity for your laptop (once)

CDK needs broad rights the first time (bootstrap creates IAM roles; the stacks create IAM roles,
RDS, a VPC, IoT rules and so on).

- [ ] Recommended: **IAM Identity Center** → create a user for yourself → assign the
      `AdministratorAccess` permission set on this account → on the laptop run
      `aws configure sso` (profile name e.g. `builderwars-prod`, region `us-east-1`).
- [ ] Simpler alternative: an IAM user with `AdministratorAccess` and an access key, stored with
      `aws configure --profile builderwars-prod`. Never commit the key.
- [ ] Check it: `aws sts get-caller-identity --profile builderwars-prod` prints the account id.
      With SSO, run `aws sso login --profile builderwars-prod` again when the session expires.

## 3. Tools on the deploying laptop

| Tool | Why | Check |
| --- | --- | --- |
| Git | clone the repo | `git --version` |
| AWS CLI v2 | credentials, IoT provisioning, invoking the Migrate Lambda | `aws --version` |
| Node.js 22+ and npm | `npx aws-cdk@2`, the web dashboard | `node --version` |
| Python 3.12 | CDK app, the API/workers workspace | `python3.12 --version` |
| uv 0.11.32 | workspace install; the deploy bundles Lambda code from `uv.lock` (Docker works as a fallback) | `uv --version` |

The deploy needs internet access to PyPI and npm (bundling downloads wheels for
`aarch64-manylinux`). No Docker is needed when `uv` is on `PATH`.

## 4. Get the code and check it

```bash
git clone https://github.com/Qdust41/builderwars && cd builderwars
uv sync --frozen          # workspace venv (.venv), Python 3.12
uv run pytest -q          # should pass before you deploy anything
```

CDK has its own virtualenv (it is not part of the uv workspace):

```bash
cd infrastructure
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
source .venv/bin/activate     # cdk.json runs `python app.py` from your PATH
python app.py                 # synth only, no AWS calls: proves the app builds
```

Keep this shell (with `.venv` active) for steps 5-7.

## 5. Bootstrap CDK (once per account + region)

```bash
export AWS_PROFILE=builderwars-prod
export CDK_DEFAULT_ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
export CDK_DEFAULT_REGION=us-east-1
export AWS_REGION=us-east-1   # required: the CDK CLI replaces CDK_DEFAULT_REGION with the SDK region
npx aws-cdk@2 bootstrap aws://$CDK_DEFAULT_ACCOUNT/us-east-1
```

- [ ] Done. This creates the `CDKToolkit` stack (an S3 asset bucket and an ECR repo, pennies).

## 6. Deploy prod

With the same variables as step 5, from `infrastructure/`:

```bash
git pull
npx aws-cdk@2 diff   -c env=prod --all
npx aws-cdk@2 deploy -c env=prod --all --outputs-file ~/.builderwars/prod-outputs.json
```

- [ ] **Always pass `-c env=prod`.** `cdk.json` defaults to `dev`, which has no database, so the
      deployed API and workers refuse to start there.
- [ ] Read the IAM/security-change prompt before saying yes. Expected and deliberate: a security
      group allowing TCP 5432 from `0.0.0.0/0` (ADR 0007), Lambda roles reading the RDS secret,
      the IoT rule role, a custom resource that calls `iot:DescribeEndpoint`.
- [ ] The first deploy takes roughly 15-20 minutes, most of it the RDS instance.

Stacks created (all prefixed `Builderwars-prod-`):

| Stack | What's in it | Outputs you'll use |
| --- | --- | --- |
| Identity | Cognito user pool `builderwars-prod-users` + app client | `UserPoolId`, `UserPoolClientId` |
| Storage | device-data and artifacts S3 buckets | |
| Messaging | ingest, jobs and commands SQS queues + DLQs | |
| Iot | device policy `builderwars-prod-device`, ingest rule `devices/+/+` → SQS | `DevicePolicyName`, `DataEndpointAddress` |
| Realtime | AppSync Events API | `EventsHttpDns`, `EventsRealtimeDns` |
| Database | VPC (public subnets only), RDS PostgreSQL 16 `db.t4g.micro`, generated secret | |
| Api | HTTP API + API Lambda | `ApiUrl` |
| Workers | DeviceIngest, CommandDispatch, Jobs, Migrate Lambdas | |
| Web | S3 bucket + CloudFront (site, and `/api/*` → the HTTP API), ACM certificate | `WebUrl`, `DistributionDomainName` |

The outputs file holds ids and URLs, not secrets, but keep it out of the repo anyway. To read
outputs again later:

```bash
aws cloudformation describe-stacks --stack-name Builderwars-prod-Api \
  --query "Stacks[0].Outputs" --output table      # same for -Identity, -Realtime, -Iot
```

## 7. Run the database migrations, then smoke test

The API and workers refuse to start until the schema is current, and nothing migrates by itself.
Do this after the first deploy and after every deploy that adds a migration.

```bash
FN=$(aws lambda list-functions --region us-east-1 \
  --query "Functions[?contains(FunctionName, 'MigrateFunction')].FunctionName | [0]" --output text)
aws lambda invoke --region us-east-1 --function-name "$FN" /dev/stdout
```

- [ ] The response lists applied migrations (`{"applied": [...]}`); an empty list later means
      nothing was pending.
- [ ] `curl <ApiUrl>/health` returns OK.
- [ ] Any other endpoint without a token returns 401, which is correct.

If you ever need the database directly (debugging only): the endpoint is in the RDS console and
the password is in the Secrets Manager secret the Database stack created. Connect with
`sslmode=require`; the server refuses non-TLS connections.

## 8. Web dashboard

Prod serves it at <https://builderwars.jimweaver.com> (see "Web app on your domain" below); every
deploy from `main` rebuilds and uploads it. To run it locally against prod instead, Vite proxies `/api` to the deployed API, so no CORS change is needed:

```bash
cd apps/web
npm ci
VITE_API_PROXY_TARGET=<ApiUrl> \
VITE_AUTH_MODE=cognito \
VITE_COGNITO_USER_POOL_ID=<UserPoolId> VITE_COGNITO_CLIENT_ID=<UserPoolClientId> \
VITE_REALTIME_PROVIDER=appsync \
VITE_APPSYNC_EVENTS_HTTP_DNS=<EventsHttpDns> VITE_APPSYNC_EVENTS_REALTIME_DNS=<EventsRealtimeDns> \
npm run dev
```

Open <http://localhost:5173>. To avoid retyping, put the same `VITE_*` lines in
`apps/web/.env.local` (git-ignored); `VITE_API_PROXY_TARGET` must stay on the command line or in
your shell, because it is read by the Vite config, not the app.

## 9. Sign up and create a project

- [ ] On the sign-in page choose **Create account**, enter email + password, then the 6-digit
      code Cognito emails you (check spam; subject "Your Builderwars verification code").
- [ ] Alternative: create the user in the Cognito console (pool `builderwars-prod-users`), which
      emails a temporary password you change on first sign-in.
- [ ] Create a project on the Projects page. You become its **owner**.

A new account sees nothing until someone adds it to a project. There is no members screen in the
web app yet; add people through the API (`POST /projects/{id}/members` with
`{"email": "...", "role": "member"}`). The person must have signed up first. For a token, sign
in to the web app and copy the `...accessToken` value from the browser's local storage
(DevTools → Application → Local Storage), then:

```bash
curl -X POST "<ApiUrl>/projects/<project-id>/members" \
  -H "Authorization: Bearer <access-token>" -H "Content-Type: application/json" \
  -d '{"email": "teammate@example.com", "role": "member"}'
```

Remember the ~50 emails/day cap on Cognito's built-in sender.

## 10. Register a device

- [ ] Open the project and register a device (a display name like "bench board 1").
- [ ] Copy the **device id** it shows, e.g. `dev_3f2a...` (36 characters). This id is the IoT
      thing name, the MQTT client id and the `DEVICE_ID` on the host. They must all match
      exactly; the IoT policy only lets a certificate connect as its own thing.

Registering creates only the database record. It does **not** create IoT credentials yet (that
is planned provisioning work), so step 11 is by hand.

## 11. Give the device an IoT identity (laptop, once per device)

With `AWS_PROFILE=builderwars-prod` set. The private key is created here and shown **once**; keep
it out of the repo and out of chat.

```bash
export DEVICE_ID=<device id from step 10>
CREDS=~/.builderwars/credentials/$DEVICE_ID
mkdir -p "$CREDS" && chmod 700 "$CREDS"

aws iot create-thing --thing-name "$DEVICE_ID"

CERT_ARN=$(aws iot create-keys-and-certificate --set-as-active \
  --certificate-pem-outfile "$CREDS/device.pem.crt" \
  --private-key-outfile     "$CREDS/private.pem.key" \
  --query certificateArn --output text)
chmod 600 "$CREDS/private.pem.key"

aws iot attach-policy        --policy-name builderwars-prod-device --target "$CERT_ARN"
aws iot attach-thing-principal --thing-name "$DEVICE_ID" --principal "$CERT_ARN"

curl -fsSo "$CREDS/AmazonRootCA1.pem" https://www.amazontrust.com/repository/AmazonRootCA1.pem

aws iot describe-endpoint --endpoint-type iot:Data-ATS --query endpointAddress --output text
# -> xxxxxxxxxxxxxx-ats.iot.us-east-1.amazonaws.com  (same as the Iot stack's DataEndpointAddress)
```

- [ ] Copy the three files to the host PC (e.g. `scp -r`), into `~/.builderwars/credentials/`,
      keeping `chmod 600` on the key. Delete the laptop copy if the laptop isn't the host.
- [ ] Note the certificate ARN somewhere private; you need it to revoke the board later
      (`aws iot update-certificate --new-status INACTIVE --certificate-id <id>`, or
      `POST /devices/{id}/revoke` once PR #4 merges).

## 12. Set up the host PC and test the board

The host is the computer the FREE-WILi is plugged into. It needs **CPython 3.10+** and, for a real
board, USB serial access.

**Option A: a clone of the repo (the dev laptop doubles as host).** Needs Python 3.12 for the
workspace. `freewili` is already a workspace dependency on `main`; add the MQTT extra:

```bash
uv sync --frozen
uv run builderwars               # what's plugged in, and what to type next
```

**Option B: a bare host (e.g. a Raspberry Pi or an older PC on 3.10).**

```bash
git clone https://github.com/Qdust41/builderwars && cd builderwars
python3 -m venv ~/.builderwars/venv && . ~/.builderwars/venv/bin/activate
pip install ./packages/device_protocol ./device freewili==0.0.51
# add the "mqtt" extra ("./device[mqtt]") only for the parked certificate path
```

Serial access (Linux): the board shows up as two ttys (`/dev/ttyACM0`, `/dev/ttyACM1`: main and
display CPU). Your user must be in the group that owns them, `dialout` on Debian/Ubuntu or
`uucp` on Arch: `sudo usermod -aG dialout $USER`, then log out and back in.

Test the board **before** involving the cloud:

```bash
builderwars ports                 # boards + serial ports, and whether you can open them
builderwars /dev/ttyACM0          # step-by-step check; prints PASS or the failing step + fix
builderwars test --watch          # press a button, see GPIO/button changes live
builderwars run /dev/ttyACM0 -n 10   # full runtime, JSON lines to stdout (no cloud yet)
```

No board (it is currently out of action)? Everything below also works with simulated sensors: just
leave out the port.

## 13. Connect the host runtime to prod

**Current path (no certificates, ADR 0009):** sign in to the CLI with your own account and let
it upload as you. You need the member role (or higher) on the project.

```bash
builderwars login                                   # web app email + password
builderwars devices                                 # find the device id
builderwars run --cloud --device-id dev_... /dev/ttyACM0   # live to the dashboard; Ctrl+C
builderwars upload dev-local --device-id dev_...    # optional: upload an earlier log CSV
```

Leave out the port to send simulated sensors instead (useful while the board is out of action).
Open the device page in the web app while it runs: telemetry and logs appear live. Dashboard
commands do not reach the board in this mode yet. Afterwards, `builderwars logs dev_...` downloads
the device's cloud logs to a CSV (`--since`, `--until`, `-o`, `--force`). The full CLI reference
is in the root [README](../README.md#the-builderwars-cli).

**Later (parked), with an IoT certificate (step 11):** put the settings in one file on the host, e.g. `~/.builderwars/prod.env` (not in the repo):

```bash
DEVICE_ID=dev_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx           # exactly the registered id
DEVICE_TRANSPORT=mqtt
IOT_ENDPOINT=xxxxxxxxxxxxxx-ats.iot.us-east-1.amazonaws.com
IOT_CERT_PATH=~/.builderwars/credentials/dev_xxxx/device.pem.crt
IOT_KEY_PATH=~/.builderwars/credentials/dev_xxxx/private.pem.key
IOT_CA_PATH=~/.builderwars/credentials/dev_xxxx/AmazonRootCA1.pem
# DEVICE_PORT=/dev/ttyACM0     # optional; implies DEVICE_SENSORS=freewili
```

Then:

```bash
set -a; . ~/.builderwars/prod.env; set +a

builderwars run -n 30                 # simulated sensors -> prod: proves the cloud path
builderwars run /dev/ttyACM0          # the real board -> prod, until Ctrl+C
```

- [ ] Always run with `DEVICE_ID` (or `--device-id`) set to the registered id. IoT refuses any
      other client id; `builderwars run` stops with a hint if it's missing.
- [ ] The runtime checks the three files exist before connecting; a bad path fails fast with the
      variable name.

To keep it running after you log out, run it under `systemd --user`, `tmux`, or similar; a
service unit isn't in the repo yet.

## 14. Verify end to end

With `builderwars run --cloud` going (step 13), work outward from the host until data appears:

1. **Host terminal:** network or API errors show there, and messages are buffered (last 1000)
   until it can send again. `builderwars whoami` confirms the sign-in; a permission error means
   your role on the project is viewer (uploading needs member or higher).
2. **Web dashboard:** the device shows `online`, a recent last-seen time, telemetry (every 5 s
   or 32 samples) and logs, live.
3. **CloudWatch Logs:** the API Lambda's log group shows the `POST /devices/{id}/messages`
   calls, no errors.
4. **Logs download:** `builderwars logs dev_... -o -` prints what the cloud stored.

Stopping the runtime with Ctrl+C sends a `shutting_down` status, so the device goes `offline`.
Commands from the device page (`ping`, `get_uptime`) don't reach a CLI-connected board yet.

With the parked MQTT path instead, check the IoT Core MQTT test client
(`devices/<device id>/#`), the ingest queue's DLQ and the `DeviceIngest` Lambda's logs; a
command then goes API → SQS → CommandDispatch Lambda → `devices/<id>/commands` → host →
`devices/<id>/responses` → ingest.

## Local log files on the host

Every `log` message the runtime sends is also appended to `~/.builderwars/logs/<device id>.csv`
(`BUILDERWARS_LOG_CSV=off` disables it, for `run` and `sim`). `builderwars show` lists them, and
`builderwars upload <file or device id> --device-id dev_...` sends one to the cloud (already
stored messages are skipped).

`builderwars to-sql <csv or device id>` makes a `.sql` dump of one file for SQLite or a scratch
PostgreSQL. It writes its own `host_device_logs` table and skips rows already present. **Don't
load it into the prod database**: the same log lines already reached prod.

## Web app on your domain

The Web stack (`infrastructure/stacks/web.py`) hosts the dashboard on CloudFront at
`config.web_domain` (prod: `builderwars.jimweaver.com`). The DNS for `jimweaver.com` stays in
Cloudflare; AWS only issues the certificate.

- `/*` serves `apps/web/dist` from a private S3 bucket; paths without a file extension (client
  routes such as `/projects/<id>`) get `index.html`.
- `/api/*` goes to the HTTP API with caching off and the `/api` prefix stripped, so the browser
  stays on one origin and the API needs no CORS.
- `scripts/build_web_prod.sh` builds the app with the Cognito and AppSync ids read from the
  deployed stacks. The deploy workflow runs it before `cdk deploy`; by hand, run it first
  (`AWS_REGION=us-east-1 scripts/build_web_prod.sh`), or the site upload is skipped.

Cloudflare records (DNS → Records), both **DNS only** (grey cloud), already set up:

| Type | Name | Target | Why |
| --- | --- | --- | --- |
| CNAME | `_d5afb458142ddaf1e5008dfb12923503.builderwars` | `_999689e01e525f85ef87231f25aa8355.wzccmgtwzk.acm-validations.aws` | ACM certificate validation and automatic renewal. Never delete it. |
| CNAME | `builderwars` | `d16lx0u1urlkrh.cloudfront.net` | The site. Target is the Web stack's `DistributionDomainName` output. |

Cloudflare's proxy (orange cloud) also works on the `builderwars` record if you set SSL/TLS to
**Full (strict)**, but it puts a second CDN in front of CloudFront for no gain.

Changing the domain: set `web_domain` in `infrastructure/config.py` and deploy. CloudFormation
creates a new certificate and waits until its validation record exists: read it from the ACM
console (us-east-1), or the stack's events, and add it in Cloudflare.

## Deploying from GitHub Actions

Once the first deploy is done, `.github/workflows/deploy.yml` keeps prod current: **merging to
`main` is the review point**. After CI passes on a push to `main`, it deploys every stack, runs the
Migrate Lambda and checks `/health` (and that `/projects` returns 401). Pull requests and other
branches never deploy. A manual redeploy of `main`: Actions → Deploy prod → Run workflow.
Deploys run one at a time; a newer merge waits for the running one.

AWS access is keyless (GitHub OIDC). One-time setup, already done for account 516268691419:

- [x] IAM OIDC provider for `token.actions.githubusercontent.com` (audience `sts.amazonaws.com`).
- [x] IAM role `builderwars-github-deploy`, trusted only for
      `repo:Qdust41@103899064/builderwars@1458014947:ref:refs/heads/main`. GitHub's token subject includes the
      numeric owner and repository ids, not just the names. Its inline policy allows only: assume the
      `cdk-hnb659fds-*` bootstrap roles in us-east-1, describe `Builderwars-prod-*` stacks, invoke
      the Migrate Lambda. CloudFormation makes the actual changes through the bootstrap
      execution role.
- [ ] GitHub: repository variable `AWS_DEPLOY_ROLE_ARN` =
      `arn:aws:iam::516268691419:role/builderwars-github-deploy`
      (Settings → Secrets and variables → Actions → Variables).
- [ ] GitHub: protect `main` (require a pull request and the CI checks), since every merge goes
      to prod.

The subject is pinned to the repository's ids, so a deleted-and-recreated repository with the same
name can't deploy. Moving the repository to another owner changes it: update the role's trust
policy. The exact subject GitHub sent is in CloudTrail (us-east-1, event
`AssumeRoleWithWebIdentity`, field `userIdentity.userName`).

## Updating prod by hand

```bash
git pull
cd infrastructure && source .venv/bin/activate
export AWS_REGION=us-east-1 CDK_DEFAULT_REGION=us-east-1
npx aws-cdk@2 diff -c env=prod --all
npx aws-cdk@2 deploy -c env=prod --all
# then step 7 again if the change added a migration (harmless if not)
```

Hosts pick up code changes with `git pull` + reinstall (option B: rerun the `pip install` line).
Certificates don't change between deploys.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `cdk deploy` fails with "uv is required to bundle Lambda code" | `uv` not on `PATH` | Install uv 0.11.32, or have Docker running |
| `cdk deploy` "SSO session expired" / `ExpiredToken` | SSO login lapsed | `aws sso login --profile builderwars-prod` |
| Stacks named `Builderwars-dev-*` appeared | `-c env=prod` was left out | `npx aws-cdk@2 destroy -c env=dev --all`, redeploy with `-c env=prod` |
| Stacks appeared in another region (e.g. us-east-2) | `AWS_REGION` not set; the CDK CLI used the profile's region | Destroy them there, `export AWS_REGION=us-east-1`, redeploy |
| Deploy workflow: "Not authorized to perform sts:AssumeRoleWithWebIdentity" | run not on `main`, trust `sub` doesn't match the token (it includes the owner/repo ids), or `AWS_DEPLOY_ROLE_ARN` wrong | Compare the trust policy with the `userIdentity.userName` of the failed `AssumeRoleWithWebIdentity` event in CloudTrail (us-east-1); check the repository variable |
| API errors right after deploy; Lambda logs say the schema is out of date | migrations not run | Step 7 |
| Web app: sign-in works, every call 401 | wrong pool/client id in `VITE_COGNITO_*` | Re-copy from the Identity stack outputs |
| No verification email | spam folder, or the 50/day cap | Create the user in the Cognito console |
| Host: MQTT connect fails or loops | `DEVICE_ID` ≠ thing name, cert not attached to the thing or the policy, cert inactive, wrong endpoint | Recheck step 11; endpoint must be the `-ats` one |
| Host: `freewili` not installed | option B without `freewili` | `pip install freewili==0.0.51` |
| Host: port permission denied | user not in `dialout`/`uucp` | `builderwars ports` prints the exact command |
| Data in the MQTT test client but not in the dashboard | ingest errors, or device not registered (quarantined after PR #4) | DeviceIngest logs, the DLQ, and the `rejected/` prefix in the device-data bucket |

## Tear down and cost

Rough monthly figures at MVP volume (<10 boards); full table in `aws-deployment.md`.

| Item | While free tier/credits last | After |
| --- | --- | --- |
| RDS `db.t4g.micro` + 20 GB | covered | ~$12-15 |
| RDS public IPv4 address | ~$3.60 | ~$3.60 |
| Secrets Manager (1 secret) | ~$0.40 | ~$0.40 |
| CloudWatch logs/alarms | cents | cents |
| IoT Core, SQS, Lambda, API Gateway, S3, AppSync, Cognito | ~$0 at this volume | ~$0-2 |
| CloudFront + ACM certificate | ~$0 (CloudFront free tier; public certificates are free) | ~$0 |

The RDS instance bills all the time, used or not. Prod keeps data on teardown:
`npx aws-cdk@2 destroy -c env=prod --all` leaves the RDS instance (deletion protection on), the S3
buckets and the Cognito pool in place; delete those by hand to stop all charges. Things and
certificates you made in step 11 are not part of any stack: delete them in the IoT console.

## Not needed for the MVP

- **Route 53:** DNS stays in Cloudflare. The API is reached through the web domain's `/api/*`
  (or its `execute-api` URL), and Cognito has no hosted-UI domain.
- **SES:** Cognito's built-in sender is used for now.
- **Secrets you create by hand:** none. The RDS password is generated into Secrets Manager.

## Before real users

- Membership check on AppSync subscriptions (`stacks/realtime.py` TODO): until it exists, any
  signed-in user could subscribe to any project's channel.
- Automated device provisioning (certificate per registered device) instead of step 11.
- Move Cognito email to SES. (The web app is hosted; the API needs no CORS because the browser
  reaches it same-origin through CloudFront.)
- Revisit the public database endpoint (VPC endpoints, or IAM DB auth, which is already enabled).
- Alarm notifications (SNS) once there is a recipient (#13).
