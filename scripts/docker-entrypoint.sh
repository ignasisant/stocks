#!/bin/sh
# Container boot: materialize the secrets file from the environment, then
# serve the app (stocks.web.server).
#
# STREAMLIT_SECRETS_TOML — full contents of .streamlit/secrets.toml ([auth],
# [app], [storage], [chat], [free_llm], [telegram]). Container hosts inject
# secrets as env vars, and stocks.secrets_env reads every key that has no env
# var of its own from that file, so we write it out here. Left unset, the app
# boots without secrets (no sign-in), or with a mounted .streamlit/secrets.toml
# when running docker locally.
set -eu
cd "$(dirname "$0")/.."

if [ -n "${STREAMLIT_SECRETS_TOML:-}" ]; then
    mkdir -p .streamlit
    umask 077
    printf '%s\n' "$STREAMLIT_SECRETS_TOML" > .streamlit/secrets.toml
    umask 022
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
