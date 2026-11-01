#!/bin/sh
# Container boot: materialize the secrets file from the environment, then
# serve the app (stocks.web.server) — or, given arguments, run those instead
# of the server: the Cloud Run job behind the Today page's market read
# (infra/cron.tf) starts this same image with `.venv/bin/stocks today-market`.
#
# STOCKS_SECRETS_TOML — full contents of secrets.toml ([auth], [app],
# [storage], [chat], [free_llm], [webpush]). Container hosts inject secrets as
# env vars, and stocks.secrets_env reads every key that has no env var of its
# own from that file, so we write it out here. STREAMLIT_SECRETS_TOML is the
# name the binding had before; a service or job still carrying it boots the
# same until a deploy with --secret moves it. Left unset, the app boots without
# secrets (no sign-in), or with a mounted secrets.toml when running docker
# locally.
set -eu
cd "$(dirname "$0")/.."

SECRETS_TOML="${STOCKS_SECRETS_TOML:-${STREAMLIT_SECRETS_TOML:-}}"
if [ -n "$SECRETS_TOML" ]; then
    umask 077
    printf '%s\n' "$SECRETS_TOML" > secrets.toml
    umask 022
fi
unset SECRETS_TOML

# A command of its own, with the secrets file already in place.
if [ $# -gt 0 ]; then
    exec "$@"
fi

# stocks.web.server is the ASGI entry point: the landing, the React shell at
# every app route, the HTTP API under /api, and 301s from the shell's old
# addresses (/next, /legacy) to the same page at the root.
exec .venv/bin/uvicorn stocks.web.server:app \
    --host 0.0.0.0 \
    --port "${PORT:-8501}" \
    --proxy-headers \
    --forwarded-allow-ips '*' \
    --no-access-log
