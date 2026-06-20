#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <env-file> <command> [args...]" >&2
  exit 2
fi

ENV_FILE="$1"
shift

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "missing env file: ${ENV_FILE}" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
. "${ENV_FILE}"
set +a

export BUDDYS_DEFAULT_OPENAI_API_KEY="${BUDDYS_DEFAULT_OPENAI_API_KEY:-${BUDDYSDEFAULTOPENAIAPIKEY:-}}"
export BUDDYS_INVITE_CODE="${BUDDYS_INVITE_CODE:-${BUDDYSINVITECODE:-}}"
export BUDDYS_DEFAULT_MODEL="${BUDDYS_DEFAULT_MODEL:-${BUDDYSDEFAULTMODEL:-MiniMax-M3}}"
export OPENAI_API_KEY="${OPENAI_API_KEY:-${OPENAIAPIKEY:-}}"
export PORT="${PORT:-${PORTNUMBER:-}}"

exec "$@"
