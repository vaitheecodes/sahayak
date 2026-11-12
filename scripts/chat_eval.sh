#!/usr/bin/env bash
# Chat eval against the real Bedrock model (backend/evals/, docs/CHAT_CONTRACT.md).
#   scripts/chat_eval.sh --estimate                 calls it would make, nothing run
#   scripts/chat_eval.sh --bot-model pro            both KBs, bot answers on Nova Pro
#   scripts/chat_eval.sh --rerun-failed <RUN>       only what failed in that run
# Needs AWS credentials for Bedrock (AWS_PROFILE in .env). Outputs in .local/chat-eval/.
set -euo pipefail
cd "$(dirname "$0")/.."
exec env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy .venv/bin/python -m backend.evals.run "$@"
