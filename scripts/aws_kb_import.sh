#!/usr/bin/env bash
# Import a reviewed KB pack into the Sahayak pilot's database
# (docs/SAHAYAK_PILOT_HOSTING.md, runbook step 15). The database is
# private, so the import runs inside the pilot VPC as a one-off ECS task
# with the API service's own image, task role and secrets:
#
#   scripts/aws_kb_import.sh PACK.json
#
#   1. reads the pack here and prints its counts (entries, terms,
#      categories, licences); nothing is sent if it isn't a readable pack;
#   2. uploads it to s3://sahayak-attachments-<account>/kb-packs/<sha256>.json
#      (private, encrypted; deleted again when this script ends, however
#      it ends);
#   3. dry run: a task runs scripts/kb_import.py --dry-run, which checks
#      the whole pack against the pilot's database (categories, terms,
#      every entry: kb_store's validation) and rolls back;
#   4. asks you to type "yes", then a second task imports it, all or
#      nothing (the same code, without --dry-run);
#   5. restarts the API service so it loads the new KB (it caches the KB
#      per process), and waits for /health.
#
# The pack is data: it is only parsed as JSON and validated, never run.
# The tasks print only `KB_IMPORT <event> name=number` lines and this
# script shows nothing else from their logs: no titles, text, ids or
# secrets. If the dry run says "invalid", run scripts/kb_import.py
# --dry-run PACK against a local copy of the pilot's categories to see
# why. Cost: two Fargate tasks of about a minute each (cents).
#
# Needs: the pilot up (database available, scripts/aws_resume.sh after a
# pause) with an image that has scripts/kb_import.py, and permission for
# ecs:RunTask plus iam:PassRole on sahayak-ecs-exec / sahayak-api-task.

source "$(dirname "$0")/aws_lib.sh"
ROOT=$(cd "$(dirname "$0")/.." && pwd)
COUNTS_LINE='^KB_IMPORT [a-z_]+( [a-z]+=[0-9]+)*$'

# The value of name=N in a KB_IMPORT line ("" if absent).
field() { printf '%s\n' "$1" | tr ' ' '\n' | sed -n "s/^$2=\([0-9]*\)$/\1/p"; }

step "Reading the pack (here; nothing is sent yet)"
guard_names
PACK=${1:-}
[ -n "$PACK" ] && [ -f "$PACK" ] || die "usage: scripts/aws_kb_import.sh PACK.json (exported with scripts/kb_import.py --export)"
LOCAL=$(python3 "$ROOT/scripts/kb_import.py" --count "$PACK" | grep -E "$COUNTS_LINE" | head -n 1 || true)
case "$LOCAL" in
  "KB_IMPORT pack "*) ;;
  *) die "$PACK isn't a readable pack (missing, over 20 MB, or not JSON); nothing was sent" ;;
esac
ENTRIES=$(field "$LOCAL" entries); TERMS=$(field "$LOCAL" terms)
[ "$ENTRIES" -gt 0 ] || die "the pack has no entries; nothing was sent"
info "$ENTRIES entries, $TERMS terms, $(field "$LOCAL" categories) categories, $(field "$LOCAL" licences) licences"
SHA=$(python3 -c 'import hashlib, sys; print(hashlib.sha256(open(sys.argv[1], "rb").read()).hexdigest())' "$PACK")

step "Checking the AWS identity and the pilot"
preflight
BUCKET=${S3_BUCKET:-$NAME-attachments-$ACCOUNT_ID}
guard_names "$BUCKET"
STATUS=$(db_status)
[ "$STATUS" = available ] || die "the database is '${STATUS:-missing}': start the pilot first (scripts/aws_resume.sh or aws_up.sh)"
SERVICE_ARN=$(service_arn)
[ -n "$SERVICE_ARN" ] || die "the API service doesn't exist: run scripts/aws_up.sh first"
TASK_DEF=$(awst ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" --query 'services[0].taskDefinition')
[ -n "$TASK_DEF" ] || die "the API service has no task definition yet"
guard_names "$SERVICE_ARN" "$TASK_DEF"
read -r CONTAINER LOG_GROUP LOG_PREFIX < <(awst ecs describe-task-definition --task-definition "$TASK_DEF" \
  --query 'taskDefinition.containerDefinitions[0].[name, logConfiguration.options."awslogs-group", logConfiguration.options."awslogs-stream-prefix"]') || true
[ -n "${CONTAINER:-}" ] && [ -n "${LOG_GROUP:-}" ] && [ -n "${LOG_PREFIX:-}" ] \
  || die "the task definition has no container with an awslogs log group"
VPC_ID=$(vpc_id)
[ -n "$VPC_ID" ] || die "no VPC $VPC_NAME"
SUBNETS=$(awst ec2 describe-subnets --filters Name=vpc-id,Values="$VPC_ID" \
  Name=tag:Name,Values="$NAME-public-a,$NAME-public-b" --query 'Subnets[].SubnetId')
API_SG=$(awst ec2 describe-security-groups --filters Name=vpc-id,Values="$VPC_ID" Name=group-name,Values="$API_SG_NAME" \
  --query 'SecurityGroups[0].GroupId')
[ -n "$SUBNETS" ] && [ -n "$API_SG" ] || die "the public subnets or the $API_SG_NAME group are missing (scripts/aws_up.sh makes them)"
info "database available; task definition ${TASK_DEF##*/}; container $CONTAINER"

# ---------------------------------------------------------------------------
KEY=kb-packs/$SHA.json
UPLOADED=0
delete_pack() {
  [ "$UPLOADED" = 1 ] || return 0
  if aws s3api delete-object --bucket "$BUCKET" --key "$KEY" --expected-bucket-owner "$ACCOUNT_ID" >/dev/null 2>&1; then
    printf '    deleted s3://%s/%s\n' "$BUCKET" "$KEY"
  else
    printf '    WARNING: could not delete s3://%s/%s; delete it by hand\n' "$BUCKET" "$KEY" >&2
  fi
}
EXIT_HOOK=delete_pack
step "Uploading the pack to s3://$BUCKET/$KEY (deleted again at the end)"
aws s3api put-object --bucket "$BUCKET" --key "$KEY" --body "$PACK" --server-side-encryption AES256 \
  --expected-bucket-owner "$ACCOUNT_ID" >/dev/null
UPLOADED=1
info "uploaded"

# Runs scripts/kb_import.py in a one-off task and leaves its KB_IMPORT
# lines (only those) in $RESULT and its exit code in $TASK_EXIT.
run_import_task() {  # extra kb_import.py arguments
  export CONTAINER BUCKET KEY
  python3 - "$TMP_DIR/overrides.json" "$@" <<'PY'
import json, os, sys
e = os.environ
command = ["python", "scripts/kb_import.py", f"s3://{e['BUCKET']}/{e['KEY']}", "--counts-only", *sys.argv[2:]]
json.dump({"containerOverrides": [{"name": e["CONTAINER"], "command": command}]}, open(sys.argv[1], "w"))
PY
  # shellcheck disable=SC2086  # SUBNETS is a list
  python3 - "$TMP_DIR/task-network.json" "$API_SG" $SUBNETS <<'PY'
import json, sys
json.dump({"awsvpcConfiguration": {"subnets": sys.argv[3:], "securityGroups": [sys.argv[2]],
                                   "assignPublicIp": "ENABLED"}}, open(sys.argv[1], "w"))
PY
  local task_arn
  task_arn=$(awst ecs run-task --cluster "$CLUSTER" --task-definition "$TASK_DEF" --launch-type FARGATE --count 1 \
    --network-configuration "file://$TMP_DIR/task-network.json" --overrides "file://$TMP_DIR/overrides.json" \
    --started-by sahayak-kb-import --tags key=project,value="$NAME" --query 'tasks[0].taskArn')
  [ -n "$task_arn" ] || die "ECS didn't start the task"
  info "task ${task_arn##*/} started; waiting for it to finish (about a minute)"
  aws ecs wait tasks-stopped --cluster "$CLUSTER" --tasks "$task_arn"
  TASK_EXIT=$(awst ecs describe-tasks --cluster "$CLUSTER" --tasks "$task_arn" --query 'tasks[0].containers[0].exitCode')
  # The log can lag the task by a few seconds: try a few times.
  local attempt
  for attempt in 1 2 3 4; do
    RESULT=$(awst logs get-log-events --log-group-name "$LOG_GROUP" \
      --log-stream-name "$LOG_PREFIX/$CONTAINER/${task_arn##*/}" --start-from-head --query 'events[].message' \
      2>/dev/null | tr '\t' '\n' | tr -d '\r' | grep -E "$COUNTS_LINE" || true)
    [ -z "$RESULT" ] || break
    [ "$attempt" = 4 ] || sleep $((POLL_SECONDS > 0 ? 5 : 0))
  done
}

# The task's line for one event ("" if it didn't print one).
event_line() { printf '%s\n' "$RESULT" | grep -E "^KB_IMPORT $1( |$)" | tail -n 1 || true; }

# ---------------------------------------------------------------------------
step "Dry run in the pilot (checks everything, writes nothing)"
run_import_task --dry-run
OK=$(event_line dry_run_ok)
if [ "${TASK_EXIT:-}" != 0 ] || [ -z "$OK" ]; then
  if [ -n "$(event_line invalid)" ]; then
    die "the pack failed validation against the pilot's database; nothing was imported (see why: scripts/kb_import.py --dry-run PACK on a local copy with the pilot's categories)"
  elif [ -n "$(event_line unreadable)" ]; then
    die "the task couldn't read the pack from S3; nothing was imported"
  fi
  die "the dry-run task failed (exit ${TASK_EXIT:-unknown}); nothing was imported"
fi
[ "$(event_line pack)" = "$LOCAL" ] || die "the task read different counts than this pack; nothing was imported"
[ "$(field "$OK" entries)" = "$ENTRIES" ] && [ "$(field "$OK" terms)" = "$TERMS" ] \
  || die "the dry run would import other counts than the pack holds; nothing was imported"
info "valid: $ENTRIES entries and $TERMS terms would be imported as approved"

printf '\nThis imports %s entries and %s terms into the pilot as approved and confirmed\n' "$ENTRIES" "$TERMS"
printf '(entries with the same id are replaced), then restarts the API service.\n'
read -r -p 'Type "yes" to import: ' ANSWER || ANSWER=""
[ "$ANSWER" = "yes" ] || die "not confirmed; nothing was imported"

# ---------------------------------------------------------------------------
step "Importing (all or nothing)"
run_import_task --yes
DONE=$(event_line imported)
if [ "${TASK_EXIT:-}" != 0 ] || [ -z "$DONE" ]; then
  die "the import task failed (exit ${TASK_EXIT:-unknown}); kb_import.py writes all or nothing, so nothing was imported"
fi
info "imported $(field "$DONE" entries) entries and $(field "$DONE" terms) terms"

# ---------------------------------------------------------------------------
step "Restarting the API service so it loads the new KB"
if aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" --force-new-deployment >/dev/null 2>"$TMP_DIR/restart.err"; then
  aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"
  API_ORIGIN=$(api_origin "$SERVICE_ARN")
  [ -z "$API_ORIGIN" ] || WANT=200 wait_for 900 "GET $API_ORIGIN/health" health_of "$API_ORIGIN"
  info "restarted"
else
  warn "couldn't restart the service ($(sed '/^[[:space:]]*$/d' "$TMP_DIR/restart.err" | head -n 1)); the KB is imported, but the API serves the old one until its task restarts (scripts/aws_pause.sh then aws_resume.sh)"
fi

step "Done"
info "Check it: sign in as a manager, open Knowledge base, then Try a ticket."
