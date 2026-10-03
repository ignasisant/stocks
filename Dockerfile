# TopStocks — container image for any container host. The live deploy is
# Cloud Run (see scripts/deploy.sh), a source deploy of this image. Serves the
# app — landing, React shell and HTTP API — on $PORT (default 8501).
#
# Secrets: bind-mount the real .streamlit/secrets.toml (what deploy/ does), or
# set STREAMLIT_SECRETS_TOML to its full contents and the entrypoint writes it
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
COPY --chown=appuser:appuser pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Bake the tiktoken BPE table into the image. Without it the first chat turn
# after every cold start downloads it (~2s, and a hard failure with no egress);
# TIKTOKEN_CACHE_DIR has to be set at runtime too, so it goes in the env.
ENV TIKTOKEN_CACHE_DIR=/home/appuser/.cache/tiktoken
RUN /app/.venv/bin/python -c "import tiktoken; tiktoken.get_encoding('o200k_base')"

# Same for the chat's embedding model (chat/memory.py): baked in, so long-term
# memory works on a cold start with no egress, against a first-recall download
# that fails closed on a locked-down revision.
#
# Saved as a plain directory rather than left in the HF cache. What the hub
# serves for this repo is model.safetensors *and* an ONNX copy of the same
# weights, and from_pretrained fetches both while reading only the first — 123MB
# of image for a file nothing opens. It cannot simply be deleted afterwards: the
# next offline load fails huggingface_hub's snapshot completeness check.
# save_pretrained writes what the model actually needs and nothing else, and the
# hub cache goes with the layer that created it.
#
# Quantized to int8 here, at build time: the float32 table is +169MB resident
# (+286MB while loading) on a 1GiB instance, and the first chat turn of every
# process loads it — on Cloud Run's in-memory filesystem, the likeliest trigger
# of the chat OOMs. The int8 table is +74MB (+93MB peak), its vectors sit at
# cosine 0.998 from the float ones (so the indexes already written keep
# matching), and the ranking on the test questions is unchanged. Quantizing at
# load time instead peaks higher than not quantizing at all.
#
# HF_HUB_OFFLINE stays on so a missing directory fails loudly at load instead of
# quietly reaching for the network on a revision that has no egress.
ENV STOCKS_EMBED_MODEL=/home/appuser/models/potion-base-32M-int8 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HUB_OFFLINE=1
RUN HF_HUB_OFFLINE=0 HF_HOME=/tmp/hf /app/.venv/bin/python -c \
    "from model2vec import StaticModel; \
     StaticModel.from_pretrained('minishlab/potion-base-32M', quantize_to='int8') \
         .save_pretrained('/home/appuser/models/potion-base-32M-int8')" \
    && rm -rf /tmp/hf

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
RUN uv sync --frozen --no-dev

EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD \
    python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/healthz')"

ENTRYPOINT ["./scripts/docker-entrypoint.sh"]
