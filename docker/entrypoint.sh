#!/bin/sh
set -e

if [ -z "${MINIMAX_API_KEY}" ] || [ "${MINIMAX_API_KEY}" = "your-minimax-api-key-here" ]; then
  echo "ERROR: MINIMAX_API_KEY is missing or still the placeholder."
  echo "Copy .env.example to .env and set your MiniMax API key, then restart."
  exit 1
fi

mkdir -p /app/backend/workspace
exec "$@"
