# Sahayak pilot hosting (plan only)

Status: **plan, nothing created.** No AWS resource exists for Sahayak yet,
and no AWS command that changes anything has been run while writing this.
Every step below that creates something billable is marked
**ASK USER FIRST**. Decisions made 2026-11-11 (see "Decisions" below):
**wait on spending** until the client's HRMS manual is in hand; only free
preparation now. Done: the sign-up switch and runbook step 2 (the
scripts are Sahayak-only).

Goal: a small, cheap, public https deployment of the Sahayak backend and
web frontend for a free pilot (about 10 users now, maybe 100-300 later),
so the mobile app's preview APK can be built against it.

Hard rule: **ticketapp-ai-aws is not touched, redeployed or shared.**
Sahayak gets its own names (`sahayak-`), VPC, ECS cluster, ECR repository,
database, S3 bucket, IAM roles, secrets, Amplify app and AWS CLI profile.
The only thing in common is the AWS account (247898554654) and the region
(ap-south-1, Mumbai).

> **The scripts are Sahayak-only now** (runbook step 2). They were copied
> from ticketapp-ai-aws with `NAME=ticketapp`, profile `ticketapp` and
> the ECS cluster `default`, so `aws_down.sh` would have deleted
> ticketapp's service and database. Now every name is `sahayak-*`, with
> profile `sahayak`, cluster `sahayak` and VPC `sahayak-vpc`, and
> `guard_names` (`scripts/aws_lib.sh`) stops a script before its first
> AWS call if the profile, a name or an ARN it finds says `ticketapp`.
> Use them only from a checkout that has this change.

Prices below are ap-south-1 on-demand, taken from `docs/AWS_DEPLOY.md`
(AWS Price List files, 3 Nov 2026) and `AWS_PLAN.md` (Bedrock, 28 Oct
2026). Figures marked "approx." weren't in those files and should be
checked before deciding.

---

## 1. Architecture

Same building blocks we proved for ticketapp-ai-aws, with separate copies:

```
 Phone (preview APK)        Browser (staff, customers)
        |                          |
        | https                    | https
        |                          v
        |              Amplify Hosting: sahayak-web
        |              https://main.<appId>.amplifyapp.com  (static React build)
        |                          | fetch https://<api>/api/*  (CORS: this origin only)
        v                          v
  ECS Express Mode service sahayak-api, cluster sahayak
  (ALB with AWS certificate: https://sahayak-api.ecs.ap-south-1.on.aws, approx. name)
        |
        |  Fargate task, 0.5 vCPU / 1 GB, 1 task, public subnet of sahayak-vpc
        |   - image from ECR sahayak-api
        |   - secrets injected at start from Secrets Manager
        |   - task role sahayak-api-task: Bedrock (Nova Lite + Pro), S3 attachments/
        |
        +--> RDS PostgreSQL 18, sahayak-db, db.t4g.micro, private subnets, SSL, encrypted
        +--> S3 sahayak-attachments-247898554654 (private, SSE-S3)
        +--> Bedrock, APAC inference profiles:
        |      apac.amazon.nova-lite-v1:0  (chat, classification, summaries, step check)
        |      apac.amazon.nova-pro-v1:0   (KB drafting, DEFAULT_DRAFTING_MODEL)
        +--> the public web (KB ingester fetches pages through SafeFetcher)
```

| Piece | Sahayak name | Notes |
|---|---|---|
| AWS CLI profile | `sahayak` | its own credentials, never `ticketapp` |
| VPC | `sahayak-vpc` (10.42.0.0/16) | 2 public subnets (tasks, ALB), 2 private subnets (DB), internet gateway, **no NAT gateway**. Free. Its own VPC means Express Mode can't put Sahayak behind a load balancer it already made for ticketapp. |
| ECS cluster | `sahayak` | Express service is created with `--cluster sahayak`, never `default` |
| ECS Express service | `sahayak-api` | 1 task (`minTaskCount 1`, `maxTaskCount 1`): the rate limiter and DB pool are per process |
| Load balancer | made by Express Mode | https with an AWS certificate; idle timeout raised to 120 s for long AI turns |
| ECR | `sahayak-api` | scan on push, immutable tags, keep last 5 |
| Image build | CodeBuild `sahayak-image-build`, bucket `sahayak-build-<account>` | x86_64 (no Docker on this Mac); built from a **clean worktree** at a chosen commit, since the build refuses uncommitted files |
| Database | `sahayak-db`, subnet group `sahayak-db` | PostgreSQL 18, db.t4g.micro, 20 GB gp3, encrypted, not public, deletion protection, 7-day automated backups, RDS-managed master password |
| Security groups | `sahayak-api`, `sahayak-db` | DB accepts 5432 only from `sahayak-api` |
| Secrets | `sahayak/app` (JWT_SECRET, ADMIN_EMAIL, ADMIN_PASSWORD) + the RDS-managed DB secret | values generated in a private temp file, never printed or committed |
| S3 | `sahayak-attachments-247898554654` | public access blocked, default encryption, objects under `attachments/` |
| IAM roles | `sahayak-ecs-exec`, `sahayak-ecs-infra`, `sahayak-api-task`, `sahayak-codebuild` | see section 4 |
| Amplify | `sahayak-web`, branch `main` | manual zip deploys, no Git connection (the repo stays private) |
| Logs | `/aws/ecs/sahayak/sahayak-api...` | 14-day retention |
| Tags | `project=sahayak` on everything | activate it as a cost-allocation tag so Billing splits Sahayak from ticketapp |

Container environment (same as ticketapp's, Sahayak values):

| Variable | Value |
|---|---|
| `APP_ENV` | `production` (strict startup checks, no demo staff) |
| `AI_PROVIDER` / `AWS_REGION` | `bedrock` / `ap-south-1` |
| `BEDROCK_MODEL_ID` | `apac.amazon.nova-lite-v1:0` |
| `AI_TIMEOUT_SECONDS` | `30` |
| `STORAGE_BACKEND` / `S3_BUCKET` / `S3_PREFIX` | `s3` / `sahayak-attachments-247898554654` / `attachments/` |
| `DB_BACKEND` / `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` | `postgres` / RDS endpoint / `5432` / `sahayak` / `sahayak_admin` |
| `DB_SSLMODE` / `DB_POOL_MAX` / `DB_POOL_TIMEOUT` | `require` / `10` / `10` |
| `ALLOWED_ORIGINS` | the Amplify URL only |
| `TRUSTED_PROXY_HOPS` | `1` |
| `EMAIL_ENABLED` | `false` |
| `KB_MODEL_CALLS_PER_RUN` / `KB_MODEL_CALLS_PER_DAY` | leave unset (60 / 300); the admin can lower them in Settings |
| secrets | `JWT_SECRET`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` from `sahayak/app`; `DB_PASSWORD` from the RDS secret |

---

## 2. Cost

### Assumptions

- Running 24/7 (730 h/month). Fargate priced as x86_64, because the
  CodeBuild image is x86_64 only. ARM64 would save about $8/month, but
  needs a two-architecture image (Docker buildx).
- 2 public subnets, so the ALB has 2 public IPv4 addresses. The default
  VPC would give 3 (+$3.65).
- Data transfer out: the first 100 GB/month to the internet is free across
  the account. A pilot sends far less.
- **Help-desk AI** (Nova Lite, $0.071 / $0.284 per 1M tokens in / out).
  - The A1 run averaged about 1,000 input and 100 output tokens per call.
  - Assume a conversation is about 15 calls (chat turns, classification,
    follow-up checks, summary, hand-off brief): about $0.0015 each.
  - Assume 10 conversations per user per month.
- **KB ingester** (drafting on Nova Pro, $0.94 / $3.76 per 1M tokens in /
  out; step check on Lite).
  - About $0.01-0.02 per page section, including a retry.
  - A 50-page manual is about 150 sections, so **$1.50-3 to build once**.
  - Re-running an unchanged page costs nothing.
  - The default daily cap of 300 model calls limits a day to roughly
    $1.50-3.

### Monthly estimate, line by line

| Item | Basis | 10 users | 100 users | 300 users |
|---|---|---|---|---|
| Fargate task | x86_64 0.5 vCPU / 1 GB: 0.5 × $0.04256 + 1 × $0.004655 per h | 18.93 | 18.93 | 18.93 (or 37.87 at 1 vCPU / 2 GB) |
| Public IPv4 on the task | $0.005/h | 3.65 | 3.65 | 3.65 |
| ALB hours | $0.0239/h | 17.45 | 17.45 | 17.45 |
| ALB LCUs | $0.008/LCU-h | ~1 | ~1.50 | ~3 |
| ALB public IPv4 × 2 | $0.005/h each | 7.30 | 7.30 | 7.30 |
| RDS db.t4g.micro, Single-AZ | $0.021/h | 15.33 | 15.33 | 15.33 (approx. 31 on db.t4g.small) |
| RDS storage 20 GB gp3 | $0.131/GB-month; backups up to the DB size free | 2.62 | 2.62 | 2.62 |
| Secrets Manager × 2 | $0.40 each | 0.80 | 0.80 | 0.80 |
| CloudWatch Logs | $0.67/GB ingested | ~0.40 | ~1 | ~2 |
| ECR | ~0.15 GB per x86 image, keep 5 | ~0.10 | ~0.10 | ~0.10 |
| CodeBuild | a few builds a month, small instance | ~0.10 (approx.) | ~0.10 | ~0.10 |
| Amplify | $0.023/GB stored, $0.15/GB served | ~0.20 | ~0.30 | ~0.50 |
| S3 attachments | storage and requests | ~0.05 | ~0.10 | ~0.30 |
| Data transfer out | under the free 100 GB | 0 | 0 | 0 |
| Bedrock, help desk | Nova Lite, ~$0.0015 per conversation | ~0.15 | ~1.50 | ~4.50 |
| Bedrock, KB ingester | Nova Pro drafting; first build one-off, then updates | ~1-3 | ~1-3 | ~1-3 |
| AWS Budgets / alarm | first 2 budgets free | 0 | 0 | 0 |
| **Total** | | **~$69-71** | **~$71-74** | **~$78-80** at the same sizes; ~$112-114 with a 1 vCPU task and db.t4g.small |

About $2.30/day running. The first month adds the one-off KB build,
covered by the KB line.

If the chat answer is moved to Nova Pro (`BEDROCK_MODEL_ID_CHAT`), that
call costs about 13x more. At 300 users that adds roughly $15-25/month.

### The biggest cost, and the cheaper options

- **The biggest cost is the always-on infrastructure, not usage.**
  - The ALB and its IPs are about $26/month, RDS about $18, and the task
    and its IP about $23.
  - The AI is under $5 even at 300 users.
  - So cost hardly changes between 10 and 300 users.
- **Cheaper options**, cheapest first:
  1. **Pause between pilot sessions** (section 3): about $29/month while
     paused instead of about $70.
  2. **Snapshot and delete between long gaps** (the `aws_down.sh`
     approach): about $0.50-4.40/month idle.
  3. **ARM64 task**: -$8/month. Needs a two-architecture Docker build.
  4. **Smaller RDS**: db.t4g.micro is already the smallest PostgreSQL
     instance. Stopping it while paused saves its $15.33 in hours.
  5. **Not recommended for the pilot**: one EC2/Lightsail box running
     the app and Postgres (about $12/month). It needs code and ops
     changes: SSL on Postgres, a reverse proxy with a certificate and a
     DNS name, backups by hand (`docs/AWS_DEPLOY.md` §0, option c).
- **Credits**: if the account has the post-July-2025 free-tier credits
  ($100-200 for 6 months), they cover the pilot's first months. I
  couldn't check this; look in Billing → Free Tier.

---

## 3. Pause and resume instead of teardown

A pause keeps the load balancer, the service definition, the database
storage and its data, so the **API URL doesn't change**. That matters
because the APK has the URL built in.

`scripts/aws_pause.sh` and `scripts/aws_resume.sh` run the steps below
(idempotent, Sahayak names only, tested against the fake CLI). The
commands are kept here so it's clear what they do.

### Pause (about 5 minutes)

```bash
export AWS_PROFILE=sahayak AWS_REGION=ap-south-1 AWS_PAGER=""
SERVICE_ARN=$(aws ecs describe-services --cluster sahayak --services sahayak-api --query 'services[0].serviceArn' --output text)
```

Scale the API to 0 tasks. Express Mode owns the scaling settings, so set
them through Express:

```bash
aws ecs update-express-gateway-service --service-arn "$SERVICE_ARN" --scaling-target '{"minTaskCount":0,"maxTaskCount":0}'
```

Not yet confirmed: that Express accepts 0. If it refuses, set the
desired count and the auto-scaling minimum directly, then re-check that
Express doesn't put it back:

```bash
aws application-autoscaling register-scalable-target --service-namespace ecs --resource-id service/sahayak/sahayak-api --scalable-dimension ecs:service:DesiredCount --min-capacity 0 --max-capacity 0
```

```bash
aws ecs update-service --cluster sahayak --service sahayak-api --desired-count 0
```

Stop the database. RDS keeps it stopped for at most **7 days**, then
starts it again by itself and bills full hours:

```bash
aws rds stop-db-instance --db-instance-identifier sahayak-db
```

**Still billed while paused** (about $29/month, $0.04/hour):

| Item | $/month |
|---|---|
| ALB hours | 17.45 |
| ALB public IPv4 × 2 | 7.30 |
| RDS storage 20 GB + backups | 2.62 |
| Secrets × 2 | 0.80 |
| ECR, logs, Amplify, S3 | ~0.50 |

**Stops billing:** the Fargate task and its IPv4 address (~$22.60), RDS
instance hours ($15.33), Bedrock.

While paused, the web page loads (Amplify), but sign-in fails with a
503 from the ALB. The mobile app shows its "can't reach the server"
error. Tell pilot users the pilot hours.

### Resume (about 10-15 minutes)

```bash
aws rds start-db-instance --db-instance-identifier sahayak-db
```

```bash
aws rds wait db-instance-available --db-instance-identifier sahayak-db
```

```bash
aws ecs update-express-gateway-service --service-arn "$SERVICE_ARN" --scaling-target '{"minTaskCount":1,"maxTaskCount":1}'
```

```bash
aws ecs wait services-stable --cluster sahayak --services sahayak-api
```

```bash
curl -s https://<api-host>/health
```

If RDS rotated the managed password while the task was stopped, the new
task reads the new one at start, so nothing else is needed. If a
*running* task loses the database after a rotation, restart it:

```bash
aws ecs update-service --cluster sahayak --service sahayak-api --force-new-deployment
```

### Pause vs the snapshot approach (`aws_down.sh` / `aws_up.sh`)

| | Always on | **Pause** (task 0, RDS stopped) | Snapshot and delete (`aws_down.sh` style) |
|---|---|---|---|
| Cost while idle | ~$70/month | **~$29/month** | ~$0.50 likely, ~$4.40 at most |
| Time to resume | none | **10-15 min** | 25-35 min (RDS restore, new service, maybe a frontend rebuild) |
| API URL | fixed | **fixed** | probably the same, not promised; if it changes, **the APK must be rebuilt** |
| Data | live | live | in the newest snapshot; writes after the snapshot started are lost |
| Limits | none | RDS restarts itself after 7 days | none |
| Risk | none | low | higher: deletes and recreates the service, DB and its password secret each time |

**Recommendation:**
- **Always on** during active pilot weeks.
- **Pause** for gaps of 1-7 days, or longer if someone re-runs the RDS
  stop every 6 days.
- **Snapshot and delete** only for a gap of several weeks, or at the end
  of the pilot.
- Under a day, leave it running: a pause saves about $0.06/hour.

---

## 4. Security for a public pilot

| Area | Plan |
|---|---|
| Secrets | `JWT_SECRET` (64 hex characters) and `ADMIN_PASSWORD` (24 random characters) are generated by the script into a private temp file and stored in Secrets Manager `sahayak/app`. The DB password is RDS-managed. ECS injects them by ARN at task start. Nothing is in the repo, the image, the task definition text, the logs or chat. The admin password is read once in the Secrets Manager console by you. |
| App's own checks | `APP_ENV=production` refuses to start with a placeholder or short `JWT_SECRET`, a weak `ADMIN_PASSWORD`, a weak or local-only DB password, or `DB_SSLMODE` weaker than `require` (`auth.check_production_config`, `db_postgres.production_problems`). It logs only the variable name. |
| Admin | One admin, created at first start from the secret, never overwritten. Change its password after the first sign-in (Account → Change password). The secret then holds a stale value, which is harmless because it isn't reused. |
| Rate limits | Login: 30/5 min per IP and 5 failures/15 min per account. Sign-up: 5/hour per IP. AI turns: 20/10 min and 200/day per customer, 60/600 per IP. `TRUSTED_PROXY_HOPS=1`, so the client IP is the one the ALB appends. All are per process, which is why the service is pinned to 1 task. |
| Public sign-up | **Closed in the pilot** (D7): `CUSTOMER_SIGNUP_ENABLED=false`, set by `aws_up.sh`. `/api/auth/customer/signup` returns 403 "Sign-up is closed. Ask your support team for an account.", `/api/meta` says `signup_open: false`, and the web app hides "Create an account" and sends `/signup` to the sign-in page. Pilot accounts are made by the admin (Users). The default elsewhere stays open. |
| CORS | `ALLOWED_ORIGINS` = the Amplify URL only, never `*`. The mobile app isn't a browser, so CORS doesn't apply to it. |
| https only | Amplify serves https. The Express ALB has an AWS certificate. Check on the first run that port 80 redirects or is closed. The mobile preview build refuses `http://` at config time (`mobile/app.config.ts`). |
| Database | Private subnets, no public address, inbound only from `sahayak-api`. Storage encrypted, SSL forced (`rds.force_ssl` on PostgreSQL 15+, and the app requires it). Deletion protection on. **7-day automated backups** (ticketapp's script used 1). A manual snapshot before every deploy. |
| IAM, task role `sahayak-api-task` | `bedrock:InvokeModel` only on `arn:aws:bedrock:ap-south-1:247898554654:inference-profile/apac.amazon.nova-lite-v1:0` and `.../apac.amazon.nova-pro-v1:0`, plus `arn:aws:bedrock:*::foundation-model/amazon.nova-lite-v1:0` and `.../amazon.nova-pro-v1:0` (the APAC profile routes to several regions). `s3:PutObject/GetObject/DeleteObject` only on `sahayak-attachments-247898554654/attachments/*`. Nothing else. ticketapp's policy allowed Lite only; KB drafting needs Pro, or it falls back to Lite every time. |
| IAM, execution role `sahayak-ecs-exec` | The AWS-managed task execution policy (ECR pull, logs), plus `secretsmanager:GetSecretValue` on exactly the two Sahayak secrets. |
| IAM, people | A temporary deployer (see section 7) whose key is deleted after setup, and a small `sahayak-ops` user or role for pause/resume and deploys (ECS update/describe, RDS stop/start/snapshot/describe, CodeBuild start, Amplify deploy, logs read). No `ticketapp*` resource ARNs in any Sahayak policy. |
| Attachments | Private bucket, SSE-S3, served only by the authorised download endpoint, no presigned URLs. |
| Logs | The app logs ids and reason codes, never message bodies, passwords or provider text. 14-day retention. |
| Spending guard | An AWS Budget on the `project=sahayak` tag, about $100/month, with emails at 25%, 50%, 80% and 100% actual and 100% forecast. Plus Cost Anomaly Detection (free). Also an account-wide budget, since ticketapp shares the bill. |
| Email | Off (`EMAIL_ENABLED=false`): no SMTP credentials to protect. Password resets are done by the admin (Users → Reset password, one-time password shown once). |
| Data | Pilot users' tickets and chats live in ap-south-1. Tell pilot users it's a pilot, and give them a short note on what's stored and who sees it. |

---

## 5. First-client flow in the deployed system

In this order. Steps 1-4 are web only, as the admin. The admin gets 403
on the KB, tickets and chats, by design.

1. **Admin signs in** at `https://main.<appId>.amplifyapp.com/login` with
   `ADMIN_EMAIL` and the password from Secrets Manager. Then change the
   password.
2. **Setup wizard** (`/admin/settings` opens on it while the product is
   unnamed):
   1. **Product**: name, one-line description, support team name.
   2. **Categories and departments**: rename or turn off the seeded
      categories (ACCOUNT, BILLING, DATA, SETUP, USAGE, ISSUE,
      INTEGRATION, OTHER) to fit the client's product. Map each one to a
      department (defaults: Product Support, Accounts & Billing,
      General). Check which ones count as high-risk under Settings →
      Routing.
   3. **Staff**: comes next, in step 3.
3. **People** (Users): create the **manager(s)** first, one per
   department, then the **support engineers**, each with their
   department. Each gets a one-time password, shown once; share it
   privately. They must change it at first sign-in.
4. **Settings to check before any AI spend**:
   - Knowledge base limits: lower model calls per run and per day if
     wanted (defaults 60 and 300).
   - AI models: drafting on Nova Pro, step check on the default.
   - SLA, if the pilot wants targets.
   - Status labels.
5. **Knowledge base**, as a manager (`/kb/sources`):
   1. Add a source: a public help page URL, an uploaded TXT/MD/PDF, or
      pasted text. Tick the "public / allowed to use" confirmation and
      add a licence note if it has one.
   2. **Estimate** (no model calls) shows the model calls the run will
      use. **Start** the run (this spends Bedrock money, capped).
   3. Review (`/kb/review`): managers and support engineers edit drafts.
      Managers approve or reject entries, confirm or merge proposed
      **terms** (approving needs them confirmed) and categories.
   4. Only **approved** entries are used by the AI. Startup logs
      `KB: <n> entries loaded`.
   5. **Chosen (D10):** build and review the KB locally, export a pack
      (`scripts/kb_import.py --export`), and import it into the pilot.
      The DB is private, so the import has to run as a one-off ECS task
      with the same image. That script doesn't exist yet: it's the one
      piece of free preparation still missing (see "Still to prepare").
6. **Try a ticket** (`/try-a-ticket`, manager or support engineer): run
   typical customer questions and check the answers and routing before
   anyone real uses it.
7. **Customers**: for a 10-person pilot, **admin-created accounts** are
   better than sign-up:
   - you know who is in;
   - each gets a one-time password and must choose their own;
   - the mobile app supports that forced change.

   Sign-up works too, but only on the web (`/signup`); the mobile app
   signs in only.
8. **What each pilot user gets**:
   - the web link (`https://main.<appId>.amplifyapp.com`);
   - their email and one-time password, sent privately;
   - for Android: the APK install link (section 6). There is no iPhone
     build in this plan; that needs an Apple Developer account
     ($99/year);
   - the pilot hours, if you pause between sessions.

---

## 6. Mobile: the preview APK against the pilot URL

The preview profile (`mobile/eas.json`) builds an installable APK with
`APP_VARIANT=preview`. `mobile/app.config.ts` then **fails the build** if
`EXPO_PUBLIC_API_URL` is missing or not `https://`. The URL is the API
origin, with no `/api` on the end, for example
`https://sahayak-api.ecs.ap-south-1.on.aws`. The APK is "Sahayak",
`com.vaitheeswaran.sahayak.preview`.

You create first:
1. The pilot backend, up and passing `/health` (runbook step 9).
2. A free Expo account at expo.dev. The free plan includes a limited
   number of cloud builds a month; check expo.dev/pricing.

Then, from `mobile/`:

```bash
npx eas-cli@latest login
```

```bash
npx eas-cli@latest init
```

`init` creates the EAS project and prints its id. Paste it into
`EAS_PROJECT_ID` in `mobile/app.config.ts` and commit it (it isn't a
secret).

```bash
npx eas-cli@latest env:create --environment preview --name EXPO_PUBLIC_API_URL --value https://<api-host> --visibility plaintext
```

Check the config locally first (it fails on http):

```bash
APP_VARIANT=preview EXPO_PUBLIC_API_URL=https://<api-host> npx expo config --type public
```

**ASK USER FIRST** (uses EAS build quota). The first build asks to
generate an Android keystore: answer yes and EAS keeps it.

```bash
npx eas-cli@latest build --platform android --profile preview
```

**Installing on a phone:**
1. EAS prints a link and a QR code. Open it on the Android phone, or
   send pilot users the link.
2. Download the APK. Android asks to allow installs from this source
   (the browser or Files app); allow it once.
3. Open Sahayak and sign in with the account the admin made.

Later builds: raise `BUILD_NUMBER` in `mobile/app.config.ts`, so Android
accepts the update over the old install. If the API URL ever changes,
change the EAS variable and rebuild.

---

## 7. Risks, and what I need from you

### Risks

| Risk | Mitigation |
|---|---|
| A copied script touches ticketapp (`NAME=ticketapp`, cluster `default`, profile `ticketapp`) | Runbook step 2 first: Sahayak names everywhere, profile `sahayak`, cluster `sahayak`, and a guard that refuses to run if the name, profile or any ARN contains `ticketapp`. Read-only inventory of ticketapp's resources before anything is created. |
| Express Mode shares a load balancer between services | Own VPC and own cluster. After creation, check that the ALB's listener rules list only `sahayak-api`. |
| API URL changes after a delete and recreate, which breaks the APK | Pause instead of delete. A custom domain (Route 53 + ACM) would pin it, if Express supports one; check that before choosing it (D6). |
| RDS starts itself after 7 days of being stopped | A calendar reminder to re-stop, or snapshot-and-delete for long gaps. The budget alert catches it. |
| Open public sign-up | Closed with `CUSTOMER_SIGNUP_ENABLED=false` (D7, done). |
| Nova Pro not invocable in this account or not in the APAC profile | One test call before deploying (runbook step 8). Drafting falls back to the default model if Pro fails, so the KB still works, just with lower quality. |
| Express rejects 0.5 vCPU / 1 GB, or `minTaskCount` 0 | Use its default size (+$19/month on x86_64). For pausing, use the `update-service` fallback in section 3. |
| Image built with someone's uncommitted work | Build only from a clean worktree at a named commit (the image tag is the commit hash). |
| Per-process rate limits and the 1-task pin limit scaling | Fine to 300 light users. More tasks need a shared limiter store first. |
| A pilot user's data or a secret leaks into logs or chat | The app logs ids only. Secrets are never printed by the scripts and never pasted into chat. |

### What I need from you

1. **The go-ahead and a monthly budget figure** (suggested $100) before
   anything is created.
2. **Deployer credentials** as AWS CLI profile `sahayak` in
   `~/.aws/credentials`, which you create yourself. Either:
   - a temporary IAM user `sahayak-deployer` with `AdministratorAccess`
     whose access key **you delete after setup**; or
   - better, a narrower policy: ECR, ECS, CodeBuild, S3 (build and
     attachments buckets), IAM (create the four `sahayak-*` roles and
     `iam:PassRole` on them), RDS, EC2 (VPC, subnets, internet gateway,
     route tables, security groups), Secrets Manager, CloudWatch Logs,
     Elastic Load Balancing (describe/modify attributes), Amplify,
     Budgets, Bedrock (`InvokeModel`, `ListInferenceProfiles`), STS.

   Then a small `sahayak-ops` profile for pause/resume and deploys.
3. **Domain:** use the default Amplify and ECS URLs (free), or name a
   domain you own.
4. **Bedrock model access:** confirm Nova Pro and Nova Lite are usable
   in this account (Bedrock console → Model access, or my one-call test
   in runbook step 8).
5. **The admin email** for the pilot.
6. ~~Approval for the script changes in runbook step 2~~: approved and
   done.

---

## Decisions for you

1. **Go or wait**, and the monthly budget (suggested $100, alerts at
   25/50/80/100% and forecast).
2. **Network**: own VPC `sahayak-vpc` (recommended, free) or the account's
   default VPC with Sahayak security groups (simpler, but shared with
   ticketapp's network).
3. **Running pattern**: always on during pilot weeks plus pause between
   (recommended), pause only, or snapshot-and-delete between sessions.
4. **Image architecture**: x86_64 via CodeBuild (no Docker needed) or
   ARM64 via Docker buildx (-$8/month, needs Docker).
5. **Chat answer model**: Nova Lite (default, cheapest) or Nova Pro for
   the customer-facing answer only (`BEDROCK_MODEL_ID_CHAT`, about +$1-25
   a month depending on users).
6. **URLs**: default ECS and Amplify URLs, or a custom domain (Route 53
   about $0.50/month plus the domain; check Express supports it first).
7. **Pilot accounts**: admin-created only, and accept that sign-up stays
   open; or approve a later backend change adding a sign-up switch.
8. **Deployer access**: a temporary admin key you delete afterwards, or
   the narrower policy.
9. **Database**: db.t4g.micro Single-AZ with 7-day backups (recommended),
   or Multi-AZ (about double the RDS cost).
10. **KB start**: ingest in the pilot directly, or build and review
    locally, then import a pack.

### Your answers (2026-11-11)

| # | Decision | Answer |
|---|---|---|
| 1 | Go or wait | **Wait on spending** until the client's HRMS manual is in hand (a deployed system with an empty KB has nothing to show). Free preparation only. Budget **$100/month** with alerts when it starts. |
| 2 | Network | Own VPC `sahayak-vpc`. |
| 3 | Running pattern | Always on during pilot weeks, paused between (`aws_pause.sh` / `aws_resume.sh`). |
| 4 | Image | x86_64 via CodeBuild (no Docker). |
| 5 | Chat model | Nova Lite. |
| 6 | URLs | Default ECS and Amplify URLs. |
| 7 | Sign-up | Admin-created pilot accounts, and a sign-up switch (done: `CUSTOMER_SIGNUP_ENABLED=false` in the pilot). |
| 8 | Deployer access | A temporary admin key, deleted after setup. |
| 9 | Database | Single-AZ, 7-day backups. |
| 10 | KB start | Build and review locally, then import the pack. |

### Still to prepare (free, no AWS)

- **Pack import into the pilot:** a script that runs `scripts/kb_import.py`
  as a one-off Fargate task in `sahayak-vpc` with the service's image,
  task role and secrets, reading the pack from the build bucket. (Or a
  manager-only "import pack" upload in the app; a backend change.)
- **Runbook step 3** just before deploying: a clean worktree of the
  chosen commit and the full suite there, on SQLite and Postgres.
- **The local KB**, once the client's manual arrives: ingest it locally
  (mock AI for a dry run, then Bedrock with your go-ahead on cost),
  review, approve, export the pack.

---

## Runbook

Every step that creates a billable resource is marked **ASK USER FIRST**:
I stop and wait for your yes on that step. Steps marked *free* still
create or change something, so they run only after the overall go-ahead
(D1).

**Phase 0: read-only (no cost, no changes)**

1. You create the `sahayak` CLI profile (section 7). I run read-only
   checks:
   - `aws sts get-caller-identity` (account 247898554654);
   - an inventory of what exists, to know exactly what not to touch:
     ECS clusters and services, RDS instances, load balancers, ECR
     repositories, secrets and Amplify apps, noting every `ticketapp*`
     one;
   - `aws bedrock list-inference-profiles` (APAC Nova Lite and Pro);
   - the CLI version and whether it has `--cpu-architecture` and
     `--cluster` for Express.

**Phase 1: repo changes (no AWS)**

2. **Done (2026-11-11).** Make the scripts Sahayak-only:
   - `NAME=sahayak`, profile `sahayak`, cluster `sahayak`;
   - own VPC creation;
   - Nova Pro in the task policy, 7-day backups;
   - a guard that stops if anything says `ticketapp`;
   - new `pause` and `resume` scripts;
   - tests against the fake AWS CLI (`tests/test_aws_scripts.py`).

   Also: the attachments bucket is created by `aws_up.sh` (ticketapp's
   was made by hand), and `aws_up.sh` stops if the service's load
   balancer isn't in `sahayak-vpc`. `aws_down.sh` reports only load
   balancers in that VPC.
3. Pick the commit to deploy. Make a clean worktree for it
   (`git worktree add --detach ../sahayak-deploy <commit>`) and run the
   full test suite there, on SQLite and Postgres.

**Phase 2: free or nearly free setup**

4. *Free:*
   - AWS Budget on `project=sahayak` and an account-wide one;
   - Cost Anomaly Detection;
   - activate the `project` cost-allocation tag.
5. *Free:* VPC `sahayak-vpc`, 2 public and 2 private subnets, internet
   gateway, route tables, security groups `sahayak-api` and `sahayak-db`,
   DB subnet group `sahayak-db`, ECS cluster `sahayak`, IAM roles
   `sahayak-ecs-exec`, `sahayak-ecs-infra`, `sahayak-api-task` and
   `sahayak-codebuild` with the policies in section 4. No NAT gateway.
6. **ASK USER FIRST** (cents a month):
   - ECR repository `sahayak-api`;
   - S3 buckets `sahayak-attachments-247898554654` and
     `sahayak-build-247898554654`;
   - secret `sahayak/app` ($0.40/month), values generated and not shown;
   - Amplify app `sahayak-web` and branch `main` (free until deployed).

**Phase 3: billable resources**

7. **ASK USER FIRST**: build the image in CodeBuild from the clean
   worktree (a few cents; about 5-10 minutes). It's pushed to ECR,
   tagged with the commit hash.
8. **ASK USER FIRST**: one Nova Pro and one Nova Lite test call from the
   `sahayak` profile (under $0.01). This confirms model access before
   anything bigger exists.
9. **ASK USER FIRST**: RDS `sahayak-db` (db.t4g.micro, ~$0.025/hour
   with storage; 10-20 minutes).
10. **ASK USER FIRST**: ECS Express service `sahayak-api` in cluster
    `sahayak` (task, ALB and IPs, ~$0.07/hour; 5-10 minutes). Then:
    - wait for `/health` to return 200;
    - raise the ALB idle timeout to 120 s and set 14-day log retention
      (free changes);
    - check that the ALB serves only Sahayak, the tasks carry the right
      security groups, and port 80 redirects or is closed.
11. **ASK USER FIRST**: build the frontend with `VITE_API_URL=<api>/api`
    and deploy it to Amplify (cents).
12. Smoke test: `scripts/aws_smoke.py --frontend ... --api ...`, then the
    signed-in check with `--admin`.
13. **ASK USER FIRST**: a manual RDS snapshot `sahayak-db-baseline`
    (cents a month).

**Phase 4: the first client (in the app)**

14. You sign in as the admin and run the setup wizard (section 5, steps
    1-4).
15. Import the locally reviewed KB pack (D10) with the one-off task
    script ("Still to prepare"); **ASK USER FIRST** (a minute of Fargate,
    cents). Later KB runs in the pilot itself: **ASK USER FIRST** for each
    one (estimate, then start).
16. Check the imported KB, confirm terms, then use Try a ticket.
17. Create the pilot customers.

**Phase 5: mobile**

18. EAS login and init; paste the project id into
    `mobile/app.config.ts` and commit. Set `EXPO_PUBLIC_API_URL` in the
    EAS preview environment and run the local config check (free).
19. **ASK USER FIRST**: `eas build --platform android --profile preview`
    (EAS quota). Install it on one phone and test, then share the link.

**Phase 6: running the pilot**

20. Deploying a new version:
    - **ASK USER FIRST**: snapshot, then build the image for the new
      commit;
    - point the service at it (`update-express-gateway-service`
      `--primary-container`);
    - wait until stable, then smoke test.
21. Between sessions: pause or resume (section 3). Re-stop RDS within 7
    days, or snapshot-and-delete for long gaps.
22. Weekly: look at the budget, the Activity log (`chat.ai_failure` /
    `ticket.ai_failure`), and the KB limits usage.
23. End of the pilot: **ASK USER FIRST**.
    - Final snapshot.
    - Delete the service, then the database, keeping the snapshot.
    - Empty and delete the buckets only if you say so.
    - Delete the deployer key and remove the budget.

## How long setup takes

| Part | Time |
|---|---|
| Phase 0: profile and read-only checks | 30 min (including your IAM setup) |
| Phase 1: script changes, tests, clean worktree and full test run | 2-3 h |
| Phases 2-3: create and deploy (mostly waiting: RDS 10-20 min, build 5-10, service 5-10, frontend 2-5) | 1-1.5 h |
| Phase 4: setup wizard, staff and customers | 30-60 min |
| Phase 4: KB ingestion and review | 1-3 h per 50 pages of help content, mostly human review |
| Phase 5: EAS setup and first APK build | 30-45 min (the build itself ~10-20 min in EAS's queue) |
| **Total** | **about one working day** to a usable pilot, plus KB review time |
