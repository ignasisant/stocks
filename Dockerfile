# TopStocks — container image for any container host. The live deploy is
# Cloud Run (see scripts/deploy.sh), a source deploy of this image. Serves the
# app — landing, React shell and HTTP API — on $PORT (default 8501).
#
# Secrets: bind-mount the real secrets.toml (what deploy/ does), or
# set STOCKS_SECRETS_TOML to its full contents and the entrypoint writes it
# to disk at boot. [storage] may alternatively come in as individual
# STOCKS_STORAGE_* env vars (see src/stocks/storage.py).

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

# HF Spaces run the container as UID 1000 regardless of USER; everything under
# /app must belong to it (data/ price caches, static/logos mirror, the
# secrets.toml bootstrap, R2 restores of watchlist.yaml + data/users/).
# Create + own /app as root FIRST: the classic (non-BuildKit) Docker builder
# used by Cloud Build makes WORKDIR dirs root-owned, so uv sync's .venv write
# would fail with EACCES unless /app is chowned to appuser beforehand.
RUN useradd -m -u 1000 appuser && mkdir -p /app && chown appuser:appuser /app
USER appuser
ENV HOME=/home/appuser
WORKDIR /app

# Dependency layer first: code edits reuse the resolved-lockfile layer.
# --no-cache on every uv step: uv's download cache is a second copy of every
# wheel already unpacked into .venv (~570MB), read by nothing at runtime.
COPY --chown=appuser:appuser pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --no-cache

# Bake the tiktoken BPE table into the image. Without it the first chat turn
# after every cold start downloads it (~2s, and a hard failure with no egress);
# TIKTOKEN_CACHE_DIR has to be set at runtime too, so it goes in the env.
ENV TIKTOKEN_CACHE_DIR=/home/appuser/.cache/tiktoken
RUN /app/.venv/bin/python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"

# Same for the chat's embedding model (chat/hybrid.py): built here, so search
# works on a cold start with no egress, and so no serving instance ever builds
# it — the cut (chat/embedding.py) downloads ~600MB and peaks near 800MB.
#
# The model is potion-multilingual-128M cut to English and Spanish, with its
# own tokenizer: ~41MB resident, against ~97MB for the English-only
# potion-base-32M it replaced and ~730MB for the uncut model under `tokenizers`.
# Built from the one file before the project is installed, so a code edit
# elsewhere reuses this layer; wordfreq (the word lists the cut keeps) and the
# download live only in this step.
ENV STOCKS_EMBED_MODEL=/home/appuser/models/potion-multilingual-128M-en-es-1
COPY --chown=appuser:appuser src/stocks/chat/embedding.py /tmp/embed/embedding.py
RUN uv run --no-sync --no-cache --with wordfreq==3.1.1 \
        python /tmp/embed/embedding.py "$STOCKS_EMBED_MODEL" \
    && rm -rf /tmp/embed

# glibc's allocator, tamed. The API serves on ~40 AnyIO worker threads plus
# per-request download pools, and by default glibc gives busy threads arenas of
# their own and raises its mmap threshold as large frames come and go — so
# freed pandas buffers stay mapped and RSS climbs in steps that never come
# down until the 1GiB instance is killed. Measured on this base image (1 CPU,
# 40 threads of pandas work): +250-300MB retained and still climbing by
# default, +30-50MB and flat with a fixed 128KiB mmap threshold (big buffers go
# straight back to the kernel on free) and two arenas.
ENV MALLOC_MMAP_THRESHOLD_=131072 \
    MALLOC_ARENA_MAX=2

COPY --chown=appuser:appuser . .
# Editable install of the project itself (default): stocks.config.PROJECT_ROOT
# resolves to /app, so data/ and watchlist.yaml live next to the source.
RUN uv sync --frozen --no-dev --no-cache

# Compressed siblings of the hashed bundle files (web/precompress.py): each
# chunk gzip'd and brotli'd once here, at the highest level, rather than
# gzip-9'd by the middleware on the one throttled CPU every time a browser
# asks for it. `brotli` is a build-time extra, not a runtime dependency.
RUN uv run --frozen --no-dev --no-cache --with brotli python -m stocks.web.precompress

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD \
    python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/healthz')"

ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
