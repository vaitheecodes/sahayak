#!/usr/bin/env bash
# Bring the Sahayak pilot up on AWS (docs/SAHAYAK_PILOT_HOSTING.md).
#
# Idempotent: every step checks what exists and only creates what's
# missing, so a failed run can simply be re-run. Free and kept: the VPC
# sahayak-vpc (2 public subnets for the load balancer and task, 2 private
# ones for the database, no NAT gateway), the ECS cluster sahayak,
# security groups, DB subnet group, IAM roles; cents a month: the app
# secret, the ECR repository, the Amplify app, RDS snapshots. Billed by
# the hour: the RDS instance (created, or restored from the newest
# snapshot) and the ECS Express service with its load balancer.
# Between pilot sessions use scripts/aws_pause.sh / aws_resume.sh;
# scripts/aws_down.sh is for the end of the pilot.
#
# Settings (environment):
#   AWS_PROFILE    default sahayak
#   AWS_REGION     default ap-south-1
#   ADMIN_EMAIL    needed once, when the app secret is first created
#   IMAGE_TAG      image to run; default: this commit's short hash, else
#                  the newest image in ECR (with a warning). Without
#                  Docker, scripts/aws_build_image.sh builds it in AWS.
#   FORCE_FRONTEND=1  rebuild and redeploy the frontend even if the API
#                  URL didn't change
#   SKIP_FRONTEND=1 / SKIP_SMOKE=1  leave out the frontend deploy / the
#                  smoke test at the end
#   CUSTOMER_SIGNUP_ENABLED  default false: pilot accounts are made by the
#                  admin; true opens public sign-up
#
# Never prints a secret: generated values go to a private temp file and
# from there to Secrets Manager; the service gets them by ARN.

source "$(dirname "$0")/aws_lib.sh"
ROOT=$(cd "$(dirname "$0")/.." && pwd)

step "Checking the AWS identity"
preflight
BUCKET=${S3_BUCKET:-$NAME-attachments-$ACCOUNT_ID}
guard_names "$BUCKET"

# ---------------------------------------------------------------------------
step "Network: VPC $VPC_NAME, subnets, security groups, DB subnet group (free)"
tags() { printf 'ResourceType=%s,Tags=[{Key=Name,Value=%s},{Key=project,Value=%s}]' "$1" "$2" "$NAME"; }
VPC_ID=$(vpc_id)
if [ -z "$VPC_ID" ]; then
  VPC_ID=$(awst ec2 create-vpc --cidr-block "$VPC_CIDR" --tag-specifications "$(tags vpc "$VPC_NAME")" \
    --query Vpc.VpcId)
  info "created VPC $VPC_NAME ($VPC_CIDR)"
else
  info "VPC $VPC_NAME exists"
fi
# DNS host names: RDS endpoints and ECR/Bedrock names resolve in the VPC.
aws ec2 modify-vpc-attribute --vpc-id "$VPC_ID" --enable-dns-hostnames '{"Value":true}' >/dev/null
IGW_ID=$(awst ec2 describe-internet-gateways --filters Name=attachment.vpc-id,Values="$VPC_ID" \
  --query 'InternetGateways[0].InternetGatewayId')
if [ -z "$IGW_ID" ]; then
  IGW_ID=$(awst ec2 create-internet-gateway --tag-specifications "$(tags internet-gateway "$NAME-igw")" \
    --query InternetGateway.InternetGatewayId)
  aws ec2 attach-internet-gateway --internet-gateway-id "$IGW_ID" --vpc-id "$VPC_ID" >/dev/null
  info "created and attached internet gateway"
fi
read -r AZ_A AZ_B < <(awst ec2 describe-availability-zones --filters Name=state,Values=available \
  --query 'AvailabilityZones[0:2].ZoneName') || true
[ -n "${AZ_A:-}" ] && [ -n "${AZ_B:-}" ] || die "fewer than 2 availability zones in $AWS_REGION"
ensure_subnet() {  # variable name cidr az
  local id
  id=$(awst ec2 describe-subnets --filters Name=vpc-id,Values="$VPC_ID" Name=tag:Name,Values="$2" \
    --query 'Subnets[0].SubnetId')
  if [ -z "$id" ]; then
    id=$(awst ec2 create-subnet --vpc-id "$VPC_ID" --cidr-block "$3" --availability-zone "$4" \
      --tag-specifications "$(tags subnet "$2")" --query Subnet.SubnetId)
    info "created subnet $2 ($3, $4)"
  fi
  printf -v "$1" '%s' "$id"
}
ensure_subnet PUBLIC_A "$NAME-public-a" 10.42.0.0/20 "$AZ_A"
ensure_subnet PUBLIC_B "$NAME-public-b" 10.42.16.0/20 "$AZ_B"
ensure_subnet PRIVATE_A "$NAME-private-a" 10.42.128.0/20 "$AZ_A"
ensure_subnet PRIVATE_B "$NAME-private-b" 10.42.144.0/20 "$AZ_B"
PUBLIC_SUBNETS="$PUBLIC_A $PUBLIC_B"     # load balancer and task (public IP, no NAT)
PRIVATE_SUBNETS="$PRIVATE_A $PRIVATE_B"  # database; the main route table has no internet route
for subnet in $PUBLIC_SUBNETS; do
  aws ec2 modify-subnet-attribute --subnet-id "$subnet" --map-public-ip-on-launch >/dev/null
done
RT_ID=$(awst ec2 describe-route-tables --filters Name=vpc-id,Values="$VPC_ID" Name=tag:Name,Values="$NAME-public" \
  --query 'RouteTables[0].RouteTableId')
if [ -z "$RT_ID" ]; then
  RT_ID=$(awst ec2 create-route-table --vpc-id "$VPC_ID" --tag-specifications "$(tags route-table "$NAME-public")" \
    --query RouteTable.RouteTableId)
  info "created public route table"
fi
if [ -z "$(awst ec2 describe-route-tables --route-table-ids "$RT_ID" \
  --query "RouteTables[0].Routes[?DestinationCidrBlock=='0.0.0.0/0'].GatewayId | [0]")" ]; then
  aws ec2 create-route --route-table-id "$RT_ID" --destination-cidr-block 0.0.0.0/0 --gateway-id "$IGW_ID" >/dev/null
  info "public subnets route to the internet gateway"
fi
ASSOCIATED=$(awst ec2 describe-route-tables --route-table-ids "$RT_ID" --query 'RouteTables[0].Associations[].SubnetId' \
  | tr '\t' ' ')
for subnet in $PUBLIC_SUBNETS; do
  case " $ASSOCIATED " in *" $subnet "*) ;; *)
    aws ec2 associate-route-table --route-table-id "$RT_ID" --subnet-id "$subnet" >/dev/null ;;
  esac
done

ensure_sg() {  # variable name description: sets the variable to the group id
  local id
  id=$(awst ec2 describe-security-groups --filters Name=vpc-id,Values="$VPC_ID" Name=group-name,Values="$2" \
    --query 'SecurityGroups[0].GroupId')
  if [ -z "$id" ]; then
    id=$(awst ec2 create-security-group --group-name "$2" --vpc-id "$VPC_ID" --description "$3" --query GroupId)
    info "created security group $2"
  else
    info "security group $2 exists"
  fi
  printf -v "$1" '%s' "$id"
}
ensure_sg API_SG "$API_SG_NAME" "Sahayak API tasks"
ensure_sg DB_SG "$DB_SG_NAME" "Sahayak RDS, from API tasks only"
RULE=$(awst ec2 describe-security-groups --group-ids "$DB_SG" \
  --query "SecurityGroups[0].IpPermissions[?FromPort==\`5432\`].UserIdGroupPairs[].GroupId | [?@=='$API_SG'] | [0]")
if [ -z "$RULE" ]; then
  aws ec2 authorize-security-group-ingress --group-id "$DB_SG" --protocol tcp --port 5432 \
    --source-group "$API_SG" >/dev/null
  info "database accepts 5432 from the API group only"
fi
if ! aws rds describe-db-subnet-groups --db-subnet-group-name "$DB_ID" >/dev/null 2>&1; then
  # shellcheck disable=SC2086  # PRIVATE_SUBNETS is a list
  aws rds create-db-subnet-group --db-subnet-group-name "$DB_ID" \
    --db-subnet-group-description "Sahayak private subnets" --subnet-ids $PRIVATE_SUBNETS >/dev/null
  info "created DB subnet group (private subnets)"
fi

# ---------------------------------------------------------------------------
step "ECS cluster $CLUSTER (free)"
if [ -n "$(awst ecs describe-clusters --clusters "$CLUSTER" --query "clusters[?status=='ACTIVE'].clusterName | [0]")" ]; then
  info "exists"
else
  aws ecs create-cluster --cluster-name "$CLUSTER" --tags key=project,value="$NAME" >/dev/null
  info "created"
fi

# ---------------------------------------------------------------------------
step "App secret $APP_SECRET_NAME (JWT key, first admin): \$0.40/month"
read -r APP_SECRET_ARN APP_SECRET_DELETED < <(awst secretsmanager describe-secret --secret-id "$APP_SECRET_NAME" \
  --query '[ARN, DeletedDate]' 2>/dev/null || true) || true
if [ -z "${APP_SECRET_ARN:-}" ]; then
  [ -n "${ADMIN_EMAIL:-}" ] || die "set ADMIN_EMAIL (your admin sign-in) for the first run"
  export ADMIN_EMAIL
  SECRET_FILE="$TMP_DIR/app-secret.json"
  ( umask 077; python3 - "$SECRET_FILE" <<'PY'
import json, os, secrets, sys
json.dump({"JWT_SECRET": secrets.token_hex(32),
           "ADMIN_PASSWORD": secrets.token_urlsafe(18),
           "ADMIN_EMAIL": os.environ["ADMIN_EMAIL"]}, open(sys.argv[1], "w"))
PY
  )
  APP_SECRET_ARN=$(awst secretsmanager create-secret --name "$APP_SECRET_NAME" \
    --description "Sahayak API: JWT signing key, first admin" \
    --secret-string "file://$SECRET_FILE" --query ARN)
  rm -f "$SECRET_FILE"
  info "created (values generated, not shown; see the doc to copy the admin password)"
elif [ -n "${APP_SECRET_DELETED:-}" ] && [ "$APP_SECRET_DELETED" != "None" ]; then
  aws secretsmanager restore-secret --secret-id "$APP_SECRET_NAME" >/dev/null
  info "restored (it was scheduled for deletion)"
else
  info "exists"
fi

# ---------------------------------------------------------------------------
step "Attachments bucket s3://$BUCKET (private, encrypted): cents a month"
if aws s3api head-bucket --bucket "$BUCKET" --expected-bucket-owner "$ACCOUNT_ID" >/dev/null 2>&1; then
  info "exists"
else
  if [ "$AWS_REGION" = us-east-1 ]; then
    aws s3api create-bucket --bucket "$BUCKET" >/dev/null
  else
    aws s3api create-bucket --bucket "$BUCKET" \
      --create-bucket-configuration LocationConstraint="$AWS_REGION" >/dev/null
  fi
  info "created"
fi
# (Re)applied every run, so a run that stopped right after create-bucket
# is completed by the next one. Files are kept: no lifecycle rule.
aws s3api put-public-access-block --bucket "$BUCKET" --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true >/dev/null
aws s3api put-bucket-encryption --bucket "$BUCKET" --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}' >/dev/null

# ---------------------------------------------------------------------------
step "Image in ECR ($SERVICE): storage \$0.10/GB-month"
ensure_ecr_repo
REGISTRY=$ACCOUNT_ID.dkr.ecr.$AWS_REGION.amazonaws.com
TAG=${IMAGE_TAG:-$(git -C "$ROOT" rev-parse --short HEAD)}
if has_image "$TAG"; then
  info "image $TAG is in ECR"
elif [ -z "${IMAGE_TAG:-}" ] && command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  [ -z "$(git -C "$ROOT" status --porcelain)" ] || warn "uncommitted changes are built into image $TAG"
  aws ecr get-login-password | docker login --username AWS --password-stdin "$REGISTRY" >/dev/null
  docker buildx build --platform linux/arm64,linux/amd64 -t "$REGISTRY/$SERVICE:$TAG" --push "$ROOT"
  info "built and pushed $TAG"
elif [ -z "${IMAGE_TAG:-}" ]; then
  LATEST=$(awst ecr describe-images --repository-name "$SERVICE" \
    --query 'sort_by(imageDetails, &imagePushedAt)[-1].imageTags[0]')
  [ -n "$LATEST" ] || die "no image in ECR and no Docker here: run scripts/aws_build_image.sh (builds it in AWS CodeBuild), then re-run"
  warn "no Docker: using the newest pushed image $LATEST, not this commit ($TAG); scripts/aws_build_image.sh builds this commit in AWS"
  TAG=$LATEST
else
  die "image $TAG isn't in ECR (scripts/aws_build_image.sh builds the current commit)"
fi
IMAGE=$REGISTRY/$SERVICE:$TAG
# ARM64 only for a multi-arch image (the Docker buildx path above). A
# CodeBuild image (scripts/aws_build_image.sh) is one x86_64 manifest.
awst ecr batch-get-image --repository-name "$SERVICE" --image-ids imageTag="$TAG" \
  --query 'images[0].imageManifest' > "$TMP_DIR/manifest.json"
IMAGE_HAS_ARM64=$(python3 -c '
import json, sys
try:
    manifest = json.load(open(sys.argv[1]))
except ValueError:
    manifest = {}
archs = {(m.get("platform") or {}).get("architecture") for m in manifest.get("manifests", [])}
print(1 if "arm64" in archs else 0)' "$TMP_DIR/manifest.json")
if [ "$IMAGE_HAS_ARM64" = 1 ]; then info "image $TAG: arm64 + amd64"; else info "image $TAG: amd64 only"; fi

# ---------------------------------------------------------------------------
step "Database $DB_ID (db.t4g.micro, private, SSL): ~\$0.025/hour while it exists"
STATUS=$(db_status)
case "$STATUS" in
  "")
    SNAPSHOT=$(db_snapshots | tail -n 1)
    if [ -n "$SNAPSHOT" ]; then
      info "restoring from snapshot $SNAPSHOT (10-20 min)"
      aws rds restore-db-instance-from-db-snapshot --db-instance-identifier "$DB_ID" \
        --db-snapshot-identifier "$SNAPSHOT" \
        --db-instance-class db.t4g.micro --storage-type gp3 \
        --db-subnet-group-name "$DB_ID" --vpc-security-group-ids "$DB_SG" \
        --no-publicly-accessible --no-multi-az --backup-retention-period "$BACKUP_DAYS" \
        --deletion-protection --copy-tags-to-snapshot \
        --tags Key=project,Value="$NAME" >/dev/null
    else
      PG_VERSION=${PG_VERSION:-$(awst rds describe-orderable-db-instance-options --engine postgres \
        --db-instance-class db.t4g.micro \
        --query "OrderableDBInstanceOptions[?starts_with(EngineVersion, '18.')].EngineVersion" \
        | tr '\t' '\n' | sort -t. -k1,1n -k2,2n | tail -n 1)}
      [ -n "$PG_VERSION" ] || die "no PostgreSQL 18 offered for db.t4g.micro; set PG_VERSION"
      info "no snapshot yet: creating an empty PostgreSQL $PG_VERSION database (10-20 min)"
      aws rds create-db-instance --db-instance-identifier "$DB_ID" \
        --engine postgres --engine-version "$PG_VERSION" \
        --db-instance-class db.t4g.micro \
        --allocated-storage 20 --storage-type gp3 --storage-encrypted \
        --db-name "$DB_NAME" --master-username "$DB_USER" --manage-master-user-password \
        --vpc-security-group-ids "$DB_SG" --db-subnet-group-name "$DB_ID" \
        --no-publicly-accessible --no-multi-az \
        --backup-retention-period "$BACKUP_DAYS" --deletion-protection --copy-tags-to-snapshot \
        --auto-minor-version-upgrade --tags Key=project,Value="$NAME" >/dev/null
    fi
    ;;
  stopped)
    info "starting the stopped instance"
    aws rds start-db-instance --db-instance-identifier "$DB_ID" >/dev/null
    ;;
  deleting) die "the database is being deleted (aws_down still running?); wait, then re-run" ;;
  *) info "status: $STATUS" ;;
esac
DB_FAIL="failed incompatible-restore incompatible-parameters incompatible-network storage-full"
WANT=available FAIL=$DB_FAIL wait_for 2700 "database" db_status
# A restored instance has no managed password secret: restore accepts
# --manage-master-user-password for Oracle only. A modify turns it on (RDS
# sets a new password and stores it in a new secret). The instance can read
# "available" before the modify starts, so wait for the secret ARN too. A
# re-run during the modify waits above, then finds the secret and skips this.
if [ "$(db_ready)" != ready ]; then
  info "turning on the RDS-managed password secret (a restore doesn't)"
  aws rds modify-db-instance --db-instance-identifier "$DB_ID" \
    --manage-master-user-password --apply-immediately >/dev/null
  WANT=ready FAIL=$DB_FAIL wait_for "${DB_SECRET_WAIT:-1200}" "database secret" db_ready
fi
read -r DB_HOST DB_SECRET_ARN < <(awst rds describe-db-instances --db-instance-identifier "$DB_ID" \
  --query 'DBInstances[0].[Endpoint.Address, MasterUserSecret.SecretArn]') || true
[ -n "${DB_SECRET_ARN:-}" ] && [ "$DB_SECRET_ARN" != "None" ] \
  || die "the database has no RDS-managed password secret"

# ---------------------------------------------------------------------------
step "IAM roles (free)"
cat > "$TMP_DIR/ecs-tasks-trust.json" <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs-tasks.amazonaws.com"},
 "Action":"sts:AssumeRole","Condition":{"StringEquals":{"aws:SourceAccount":"$ACCOUNT_ID"}}}]}
JSON
cat > "$TMP_DIR/ecs-infra-trust.json" <<'JSON'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ecs.amazonaws.com"},
 "Action":"sts:AssumeRole"}]}
JSON
ROLES_CREATED=0
ensure_role() {  # name trust-file
  if aws iam get-role --role-name "$1" >/dev/null 2>&1; then
    info "role $1 exists"
  else
    aws iam create-role --role-name "$1" --assume-role-policy-document "file://$2" >/dev/null
    ROLES_CREATED=1
    info "created role $1"
  fi
}
ensure_role "$EXEC_ROLE" "$TMP_DIR/ecs-tasks-trust.json"
ensure_role "$INFRA_ROLE" "$TMP_DIR/ecs-infra-trust.json"
ensure_role "$TASK_ROLE" "$TMP_DIR/ecs-tasks-trust.json"
aws iam attach-role-policy --role-name "$EXEC_ROLE" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy >/dev/null
aws iam attach-role-policy --role-name "$INFRA_ROLE" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AmazonECSInfrastructureRoleforExpressGatewayServices >/dev/null
# The DB secret is new on every restore, so this is rewritten each run:
# the execution role reads exactly the two current secrets.
cat > "$TMP_DIR/exec-policy.json" <<JSON
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Action":"secretsmanager:GetSecretValue",
 "Resource":["$APP_SECRET_ARN","$DB_SECRET_ARN"]}]}
JSON
aws iam put-role-policy --role-name "$EXEC_ROLE" --policy-name read-sahayak-secrets \
  --policy-document "file://$TMP_DIR/exec-policy.json" >/dev/null
cat > "$TMP_DIR/task-policy.json" <<JSON
{"Version":"2012-10-17","Statement":[
 {"Sid":"Bedrock","Effect":"Allow","Action":["bedrock:InvokeModel"],
  "Resource":["arn:aws:bedrock:$AWS_REGION:$ACCOUNT_ID:inference-profile/$BEDROCK_MODEL",
              "arn:aws:bedrock:$AWS_REGION:$ACCOUNT_ID:inference-profile/$DRAFTING_MODEL",
              "arn:aws:bedrock:*::foundation-model/${BEDROCK_MODEL#apac.}",
              "arn:aws:bedrock:*::foundation-model/${DRAFTING_MODEL#apac.}"]},
 {"Sid":"Attachments","Effect":"Allow","Action":["s3:PutObject","s3:GetObject","s3:DeleteObject"],
  "Resource":"arn:aws:s3:::$BUCKET/attachments/*"},
 {"Sid":"KbPacks","Effect":"Allow","Action":"s3:GetObject",
  "Resource":"arn:aws:s3:::$BUCKET/kb-packs/*"}]}
JSON
aws iam put-role-policy --role-name "$TASK_ROLE" --policy-name sahayak-api \
  --policy-document "file://$TMP_DIR/task-policy.json" >/dev/null
info "execution role reads the 2 secrets; task role: Nova Lite and Pro, attachments/ and (read) kb-packs/ in S3"
if [ "$ROLES_CREATED" = 1 ] && [ "$POLL_SECONDS" -gt 0 ]; then
  info "waiting 15 s for the new roles to become usable"
  sleep 15
fi

# ---------------------------------------------------------------------------
step "Amplify app $AMPLIFY_NAME (free until something is deployed)"
AMPLIFY_APP_ID=$(awst amplify list-apps --query "apps[?name=='$AMPLIFY_NAME'].appId | [0]")
if [ -z "$AMPLIFY_APP_ID" ]; then
  AMPLIFY_APP_ID=$(awst amplify create-app --name "$AMPLIFY_NAME" --platform WEB \
    --custom-rules '[{"source":"</^[^.]+$|\\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|woff2|ttf|map|json|webp)$)([^.]+$)/>","target":"/index.html","status":"200"}]' \
    --query app.appId)
  info "created"
fi
if ! aws amplify get-branch --app-id "$AMPLIFY_APP_ID" --branch-name main >/dev/null 2>&1; then
  aws amplify create-branch --app-id "$AMPLIFY_APP_ID" --branch-name main >/dev/null
  info "created branch main"
fi
FRONTEND_URL=https://main.$AMPLIFY_APP_ID.amplifyapp.com
info "frontend: $FRONTEND_URL (stable: it is the CORS origin)"

# ---------------------------------------------------------------------------
step "API service $SERVICE (ECS Express: Fargate task + load balancer): ~\$0.07/hour"
CUSTOMER_SIGNUP_ENABLED=${CUSTOMER_SIGNUP_ENABLED:-false}
export IMAGE AWS_REGION BUCKET DB_HOST DB_NAME DB_USER FRONTEND_URL APP_SECRET_ARN DB_SECRET_ARN BEDROCK_MODEL
export CUSTOMER_SIGNUP_ENABLED
python3 - "$TMP_DIR/container.json" <<'PY'
import json, os, sys
e = os.environ
env = {
    "APP_ENV": "production", "AI_PROVIDER": "bedrock", "AWS_REGION": e["AWS_REGION"],
    "BEDROCK_MODEL_ID": e["BEDROCK_MODEL"], "AI_TIMEOUT_SECONDS": "30",
    "STORAGE_BACKEND": "s3", "S3_BUCKET": e["BUCKET"], "S3_PREFIX": "attachments/",
    "DB_BACKEND": "postgres", "DB_HOST": e["DB_HOST"], "DB_PORT": "5432",
    "DB_NAME": e["DB_NAME"], "DB_USER": e["DB_USER"], "DB_SSLMODE": "require",
    "DB_POOL_MAX": "10", "DB_POOL_TIMEOUT": "10",
    "ALLOWED_ORIGINS": e["FRONTEND_URL"], "TRUSTED_PROXY_HOPS": "1", "EMAIL_ENABLED": "false",
    "CUSTOMER_SIGNUP_ENABLED": e["CUSTOMER_SIGNUP_ENABLED"],
}
app, dbs = e["APP_SECRET_ARN"], e["DB_SECRET_ARN"]
secrets = [
    {"name": "JWT_SECRET", "valueFrom": f"{app}:JWT_SECRET::"},
    {"name": "ADMIN_EMAIL", "valueFrom": f"{app}:ADMIN_EMAIL::"},
    {"name": "ADMIN_PASSWORD", "valueFrom": f"{app}:ADMIN_PASSWORD::"},
    {"name": "DB_PASSWORD", "valueFrom": f"{dbs}:password::"},
]
json.dump({"image": e["IMAGE"], "containerPort": 8000,
           "environment": [{"name": k, "value": v} for k, v in env.items()],
           "secrets": secrets}, open(sys.argv[1], "w"))
PY
DB_PASSWORD_REF="$DB_SECRET_ARN:password::"
SERVICE_ARN=$(service_arn)
if [ -z "$SERVICE_ARN" ]; then
  ARCH=()
  if [ "$IMAGE_HAS_ARM64" = 1 ] \
    && aws ecs create-express-gateway-service help 2>/dev/null | grep -q -- '--cpu-architecture'; then
    ARCH=(--cpu-architecture ARM64)
  fi
  # shellcheck disable=SC2086  # PUBLIC_SUBNETS is a list
  python3 - "$TMP_DIR/network.json" "$API_SG" $PUBLIC_SUBNETS <<'PY'
import json, sys
json.dump({"securityGroups": [sys.argv[2]], "subnets": sys.argv[3:]}, open(sys.argv[1], "w"))
PY
  SERVICE_ARN=$(awst ecs create-express-gateway-service --cluster "$CLUSTER" --service-name "$SERVICE" \
    --execution-role-arn "arn:aws:iam::$ACCOUNT_ID:role/$EXEC_ROLE" \
    --infrastructure-role-arn "arn:aws:iam::$ACCOUNT_ID:role/$INFRA_ROLE" \
    --task-role-arn "arn:aws:iam::$ACCOUNT_ID:role/$TASK_ROLE" \
    --cpu 512 --memory 1024 ${ARCH[@]+"${ARCH[@]}"} \
    --health-check-path /health \
    --scaling-target '{"minTaskCount":1,"maxTaskCount":1}' \
    --network-configuration "file://$TMP_DIR/network.json" \
    --primary-container "file://$TMP_DIR/container.json" \
    --tags key=project,value="$NAME" \
    --query service.serviceArn)
  info "created (${ARCH[*]:-x86_64}); the first deployment takes 5-10 min"
else
  read -r CUR_IMAGE CUR_DB_REF < <(awst ecs describe-express-gateway-service --service-arn "$SERVICE_ARN" \
    --query "service.activeConfigurations[0].primaryContainer.[image, secrets[?name=='DB_PASSWORD'].valueFrom | [0]]") || true
  if [ "${CUR_IMAGE:-}" != "$IMAGE" ] || [ "${CUR_DB_REF:-}" != "$DB_PASSWORD_REF" ]; then
    aws ecs update-express-gateway-service --service-arn "$SERVICE_ARN" \
      --primary-container "file://$TMP_DIR/container.json" >/dev/null
    info "updated (new image or database secret); rolling out"
  else
    info "exists and is current"
  fi
fi
info "waiting for the service to be stable"
guard_names "$SERVICE_ARN" "$APP_SECRET_ARN" "$DB_SECRET_ARN"
aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"

API_ORIGIN=$(api_origin "$SERVICE_ARN")
[ -n "$API_ORIGIN" ] || die "the service has no URL yet; re-run in a few minutes"
WANT=200 wait_for 900 "GET $API_ORIGIN/health" health_of "$API_ORIGIN"

# Long AI turns: the load balancer's idle timeout 60 s -> 120 s (uvicorn's
# keep-alive is 130 s). Found through the service's target group.
TG_ARN=$(awst ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" \
  --query 'services[0].loadBalancers[0].targetGroupArn')
LB_ARN=""
[ -z "$TG_ARN" ] || LB_ARN=$(awst elbv2 describe-target-groups --target-group-arns "$TG_ARN" \
  --query 'TargetGroups[0].LoadBalancerArns[0]')
if [ -n "$LB_ARN" ]; then
  # Express may share a load balancer between services: Sahayak's must be
  # in Sahayak's VPC, so it can't be one serving another app.
  LB_VPC=$(awst elbv2 describe-load-balancers --load-balancer-arns "$LB_ARN" --query 'LoadBalancers[0].VpcId')
  [ "$LB_VPC" = "$VPC_ID" ] || die "the service's load balancer is in VPC '$LB_VPC', not $VPC_NAME ($VPC_ID); stop and check it in the console"
  aws elbv2 modify-load-balancer-attributes --load-balancer-arn "$LB_ARN" \
    --attributes Key=idle_timeout.timeout_seconds,Value=120 >/dev/null
  info "load balancer idle timeout 120 s"
else
  warn "load balancer not found; set its idle timeout to 120 s in the console"
fi
LOG_GROUP=$(awst ecs describe-express-gateway-service --service-arn "$SERVICE_ARN" \
  --query 'service.activeConfigurations[0].primaryContainer.awsLogsConfiguration.logGroup')
if [ -n "$LOG_GROUP" ]; then
  aws logs put-retention-policy --log-group-name "$LOG_GROUP" --retention-in-days 14 >/dev/null
  info "logs: $LOG_GROUP (14 days)"
fi

# ---------------------------------------------------------------------------
step "Frontend on Amplify (VITE_API_URL=$API_ORIGIN/api)"
# The API URL deployed last time is kept on the branch (API_URL); the
# frontend is only rebuilt when it changed.
DEPLOYED=$(awst amplify get-branch --app-id "$AMPLIFY_APP_ID" --branch-name main \
  --query 'branch.environmentVariables.API_URL')
if [ "${SKIP_FRONTEND:-0}" = 1 ]; then
  info "skipped (SKIP_FRONTEND=1)"
elif [ "$DEPLOYED" = "$API_ORIGIN/api" ] && [ "${FORCE_FRONTEND:-0}" != 1 ]; then
  info "already built for this API URL"
else
  need npm; need zip; need curl
  ( cd "$ROOT/frontend"
    [ -d node_modules ] || npm ci --no-audit --no-fund
    VITE_API_URL="$API_ORIGIN/api" npm run build >/dev/null
    cd dist && zip -qr "$TMP_DIR/web.zip" . )
  read -r JOB_ID UPLOAD_URL < <(awst amplify create-deployment --app-id "$AMPLIFY_APP_ID" --branch-name main \
    --query '[jobId, zipUploadUrl]') || true
  [ -n "${JOB_ID:-}" ] && [ -n "${UPLOAD_URL:-}" ] || die "Amplify didn't return an upload URL"
  curl -sf -T "$TMP_DIR/web.zip" "$UPLOAD_URL" >/dev/null || die "uploading the frontend failed"
  aws amplify start-deployment --app-id "$AMPLIFY_APP_ID" --branch-name main --job-id "$JOB_ID" >/dev/null
  job_status() { awst amplify get-job --app-id "$AMPLIFY_APP_ID" --branch-name main --job-id "$JOB_ID" \
    --query 'job.summary.status'; }
  WANT=SUCCEED FAIL="FAILED CANCELLED" wait_for 600 "frontend deployment" job_status
  aws amplify update-branch --app-id "$AMPLIFY_APP_ID" --branch-name main \
    --environment-variables API_URL="$API_ORIGIN/api" >/dev/null
fi

# ---------------------------------------------------------------------------
step "Smoke test (no sign-in)"
if [ "${SKIP_SMOKE:-0}" = 1 ]; then
  info "skipped (SKIP_SMOKE=1)"
else
  python3 "$ROOT/scripts/aws_smoke.py" --frontend "$FRONTEND_URL" --api "$API_ORIGIN" \
    || die "smoke test failed (the stack is up and billing; fix it or run scripts/aws_down.sh)"
fi

step "Up"
info "frontend: $FRONTEND_URL"
info "API:      $API_ORIGIN"
info "Billing by the hour now (~\$0.10/hour). Between pilot sessions: scripts/aws_pause.sh."
info "Signed-in checks: python3 scripts/aws_smoke.py --frontend $FRONTEND_URL --api $API_ORIGIN --admin"
