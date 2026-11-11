#!/usr/bin/env bash
# Resume the Sahayak pilot after scripts/aws_pause.sh
# (docs/SAHAYAK_PILOT_HOSTING.md, section 3): start the database, wait for
# it, then run the API service's one task again and wait for /health.
# Same URL, same data; about 10-15 minutes. Billing by the hour again
# (~$0.10/hour) from here.
#
# Needs both the service and the database to exist: after
# scripts/aws_down.sh use scripts/aws_up.sh instead (it restores the
# newest snapshot).
#
# Idempotent: re-run it after a failure.

source "$(dirname "$0")/aws_lib.sh"

step "Checking the AWS identity"
preflight
SERVICE_ARN=$(service_arn)
guard_names "$SERVICE_ARN"
STATUS=$(db_status)
[ -n "$SERVICE_ARN" ] && [ -n "$STATUS" ] \
  || die "the service or the database doesn't exist (taken down?): run scripts/aws_up.sh"

# ---------------------------------------------------------------------------
step "Database $DB_ID: start (~\$0.025/hour)"
DB_FAIL="failed incompatible-restore incompatible-parameters incompatible-network storage-full"
case "$STATUS" in
  available) info "already running" ;;
  stopped)
    aws rds start-db-instance --db-instance-identifier "$DB_ID" >/dev/null
    info "starting (5-10 min)"
    ;;
  stopping) WANT=stopped FAIL="$DB_FAIL" wait_for 1800 "database" db_status
    aws rds start-db-instance --db-instance-identifier "$DB_ID" >/dev/null ;;
  *) info "status: $STATUS" ;;
esac
WANT=available FAIL="$DB_FAIL" wait_for 1800 "database" db_status

# ---------------------------------------------------------------------------
step "API service $SERVICE: 1 task (~\$0.07/hour with the load balancer)"
if aws ecs update-express-gateway-service --service-arn "$SERVICE_ARN" \
    --scaling-target '{"minTaskCount":1,"maxTaskCount":1}' >/dev/null 2>"$TMP_DIR/scale.err"; then
  info "scaling target 1-1"
else
  warn "Express refused the scaling target ($(sed '/^[[:space:]]*$/d' "$TMP_DIR/scale.err" | head -n 1)); using the ECS service count"
  aws application-autoscaling register-scalable-target --service-namespace ecs \
    --resource-id "service/$CLUSTER/$SERVICE" --scalable-dimension ecs:service:DesiredCount \
    --min-capacity 1 --max-capacity 1 >/dev/null
  aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" --desired-count 1 >/dev/null
  info "desired count 1"
fi
aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"

API_ORIGIN=$(api_origin "$SERVICE_ARN")
[ -n "$API_ORIGIN" ] || die "the service has no URL; check it in the console"
WANT=200 wait_for 900 "GET $API_ORIGIN/health" health_of "$API_ORIGIN"

step "Running"
info "API: $API_ORIGIN"
info "Billing by the hour again (~\$0.10/hour). Pause: scripts/aws_pause.sh"
