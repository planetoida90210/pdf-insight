# Build stage: uv installs the locked dependencies into /app/.venv.
FROM python:3.12-slim-bookworm AS build

COPY --from=ghcr.io/astral-sh/uv:0.11.19 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Runtime: the official Python image with the virtualenv only, no uv and no package cache.
FROM python:3.12-slim-bookworm

# OMP_THREAD_LIMIT=1: on one vCPU, Tesseract's extra OpenMP threads only slow it down.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8000 \
    OMP_THREAD_LIMIT=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        tesseract-ocr \
        tesseract-ocr-pol \
        tesseract-ocr-eng \
        ca-certificates \
        tini \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=build /app/.venv ./.venv
COPY app ./app

# Code and packages stay owned by root: the server process can read them, not change them.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000

# tini as PID 1 passes SIGTERM on to uvicorn and reaps the Tesseract processes left behind
# when an extraction worker is killed at its deadline.
ENTRYPOINT ["tini", "--"]
CMD ["sh", "-c", "exec /app/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --no-server-header"]
