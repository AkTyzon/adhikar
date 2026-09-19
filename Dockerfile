# syntax=docker/dockerfile:1

# Multi-stage: the build stage carries compilers and caches, the runtime stage
# carries neither. Everything that is only needed to install is left behind.

# ----------------------------------------------------------------- build
FROM python:3.12-slim-bookworm AS build

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Dependency metadata is copied before the source so that a source-only change
# does not invalidate the dependency layer.
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install ".[anthropic]"

# ----------------------------------------------------------------- runtime
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    ADHIKAR_ENVIRONMENT=production \
    ADHIKAR_DATABASE_URL=postgresql+asyncpg://unset/unset

# Run as an unprivileged user with no login shell. A container process that does
# not need root should never have it, and a legal-document analyser never does.
RUN groupadd --system --gid 1001 adhikar \
 && useradd --system --uid 1001 --gid adhikar --no-create-home --shell /usr/sbin/nologin adhikar \
 && apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/venv /opt/venv

# No source is copied here: the build stage installed the package into the venv,
# and the wheel carries its data files (clause catalogues, prompts, templates,
# static assets). Copying src/ as well would leave two copies and make it unclear
# which one is authoritative.
WORKDIR /app

USER adhikar

EXPOSE 8000

# The health endpoint exercises configuration loading and the clause catalogue,
# so a container that answers it has genuinely started rather than merely bound
# a port.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/health || exit 1

# Documents live in memory, so a worker restart drops them by design. One worker
# keeps a session's document reachable; scaling out needs a shared store, which
# is a deliberate decision rather than a default (see src/adhikar/store.py).
CMD ["uvicorn", "adhikar.api.app:create_app", \
     "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--no-server-header", "--proxy-headers"]
