# Reproducible install: dependency graph from uv.lock (--frozen) with bytecode compile.
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.3 /uv /usr/local/bin/uv

WORKDIR /build
COPY pyproject.toml uv.lock ./
COPY src/ src/

ENV UV_COMPILE_BYTECODE=1
RUN uv sync --frozen --no-dev


FROM python:3.12-slim

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
