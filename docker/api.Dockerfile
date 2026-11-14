# Local/dev image for the API. Build from the repository root:
#   docker build -f docker/api.Dockerfile -t builderwars-api .
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY packages ./packages
COPY apps/api ./apps/api
COPY apps/workers ./apps/workers
COPY device ./device
RUN uv sync --frozen --no-dev --package bw-api

RUN useradd --system --uid 10001 app
USER app
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
