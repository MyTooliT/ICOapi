#!/bin/sh
set -e

# Load the first *.env file found in icoapi/config
ENV_FILE="$(ls icoapi/config/*.env 2>/dev/null | head -n 1)"

if [ -n "$ENV_FILE" ]; then
  echo "Loading env from $ENV_FILE"
  set -a
  . "$ENV_FILE"
  set +a
else
  echo "No .env file found in icoapi/config"
fi

exec "$@"
