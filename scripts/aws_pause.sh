#!/usr/bin/env bash
# Pause the Sahayak pilot between sessions (docs/SAHAYAK_PILOT_HOSTING.md,
# section 3): the API service goes to 0 tasks and the database is stopped.
# Nothing is deleted, so the data, the API URL (which the mobile APK was
# built against) and the frontend stay; scripts/aws_resume.sh brings it
# back in 10-15 minutes.
#
# Still billed while paused, about $29/month: the load balancer and its
# public IPs, the database storage and backups, the secrets, ECR and logs.
# RDS starts a stopped database by itself after 7 days: re-run this
# script before then (it stops it again), or use scripts/aws_down.sh for
# a long gap.
#
# Idempotent: re-run it after a failure; what is already paused is skipped.
# Pilot users can't sign in while it is paused: tell them first.

source "$(dirname "$0")/aws_lib.sh"

step "Checking the AWS identity"
preflight
SERVICE_ARN=$(service_arn)
guard_names "$SERVICE_ARN"
STATUS=$(db_status)
[ -n "$SERVICE_ARN" ] || [ -n "$STATUS" ] || die "there is no Sahayak service or database to pause (scripts/aws_up.sh creates them)"

# ---------------------------------------------------------------------------
step "API service $SERVICE: 0 tasks"
if [ -z "$SERVICE_ARN" ]; then
  info "no service"
elif aws ecs update-express-gateway-service --service-arn "$SERVICE_ARN" \
    --scaling-target '{"minTaskCount":0,"maxTaskCount":0}' >/dev/null 2>"$TMP_DIR/scale.err"; then
  info "scaling target 0-0"
else
  # Express may refuse a minimum of 0: set the service's own scaling
  # range and count instead (the same service, through plain ECS).
  warn "Express refused 0 tasks ($(sed '/^[[:space:]]*$/d' "$TMP_DIR/scale.err" | head -n 1)); using the ECS service count"
  aws application-autoscaling register-scalable-target --service-namespace ecs \
    --resource-id "service/$CLUSTER/$SERVICE" --scalable-dimension ecs:service:DesiredCount \
    --min-capacity 0 --max-capacity 0 >/dev/null
  aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" --desired-count 0 >/dev/null
  info "desired count 0"
fi
if [ -n "$SERVICE_ARN" ]; then
  aws ecs wait services-stable --cluster "$CLUSTER" --services "$SERVICE"
  info "no tasks running"
fi

# ---------------------------------------------------------------------------
step "Database $DB_ID: stop"
case "$STATUS" in
  "") info "no database" ;;
  stopped) info "already stopped" ;;
  available)
    aws rds stop-db-instance --db-instance-identifier "$DB_ID" >/dev/null
    WANT=stopped FAIL="failed storage-full" wait_for 1800 "database" db_status
    ;;
  stopping) WANT=stopped FAIL="failed storage-full" wait_for 1800 "database" db_status ;;
  *) die "the database is '$STATUS'; wait until it is available, then re-run" ;;
esac

step "Paused"
info "Still billed: about \$29/month (load balancer, public IPs, storage, secrets)."
if [ -n "$STATUS" ]; then
  info "RDS starts the database again by itself on $(date -u -v+7d +%Y-%m-%d 2>/dev/null || date -u -d '+7 days' +%Y-%m-%d) (UTC): re-run this script before then."
fi
info "Resume: scripts/aws_resume.sh"
