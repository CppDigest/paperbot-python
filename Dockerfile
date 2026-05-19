# Reproducible install: dependency graph from uv.lock (--frozen) with bytecode compile.
# Update python digest when intentionally upgrading the base image (see CONTRIBUTING.md).
FROM python:3.12-slim@sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461 AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.3 /uv /usr/local/bin/uv

WORKDIR /build
COPY pyproject.toml uv.lock ./
COPY src/ src/

ENV UV_COMPILE_BYTECODE=1
RUN uv sync --frozen --no-dev --no-editable

# Dev deps for CI in-container pytest (target: test).
FROM builder AS test-builder
COPY tests/ tests/
RUN uv sync --frozen --extra dev --no-editable


FROM python:3.12-slim@sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461 AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash paperscout

WORKDIR /app
COPY --from=builder /build/.venv /app/.venv
COPY src/ src/

ENV PATH="/app/.venv/bin:$PATH" \
    VIRTUAL_ENV="/app/.venv"

RUN mkdir -p /app/data && chown paperscout:paperscout /app/data

USER paperscout

EXPOSE 3000 8080

ENTRYPOINT ["python", "-m", "paperscout"]


FROM runtime AS test

USER root
COPY --from=test-builder /build/.venv /app/.venv
COPY --from=test-builder /build/tests /app/tests
RUN chown -R paperscout:paperscout /app/.venv /app/tests
USER paperscout

# Default image for production (must remain the final stage).
FROM runtime AS production
