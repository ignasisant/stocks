#!/bin/sh
# Container boot: materialize the secrets file from the environment, then
# serve the app (stocks.web.server).
#
# STREAMLIT_SECRETS_TOML — full contents of .streamlit/secrets.toml ([auth],
# [app], [storage], [chat], [free_llm], [telegram]). Container hosts inject
# secrets as env vars while st.secrets only reads files, so we write it out
# here. Left unset, the app boots without secrets (auth setup screen), or
# with a mounted .streamlit/secrets.toml when running docker locally.
set -eu
cd "$(dirname "$0")/.."

if [ -n "${STREAMLIT_SECRETS_TOML:-}" ]; then
    mkdir -p .streamlit
    umask 077
    printf '%s\n' "$STREAMLIT_SECRETS_TOML" > .streamlit/secrets.toml
    umask 022
fi

# server.py, not app.py: it is the ASGI entry point that serves the React
# shell at every route, redirects /next, and mounts the Streamlit app
# read-only at /legacy (`st.App` detects the module-level mount and serves it
# directly). Pointing this at app.py still boots a working dashboard, just
# with no React shell, no landing SEO, and Streamlit back on every route.
exec .venv/bin/uvicorn stocks.web.server:app \
    --host 0.0.0.0 \
    --port "${PORT:-8501}" \
    --proxy-headers \
    --forwarded-allow-ips '*' \
    --no-access-log
