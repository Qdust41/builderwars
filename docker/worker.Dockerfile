# Worker image (future ECS Fargate target for long-running jobs). Build from the repo root:
#   docker build -f docker/worker.Dockerfile -t builderwars-worker .
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY packages ./packages
COPY apps/api ./apps/api
COPY apps/workers ./apps/workers
COPY device ./device
RUN uv sync --frozen --no-dev --package bw-workers

RUN useradd --system --uid 10001 app
USER app
# Local harness by default: reads JSON lines on stdin. TODO: queue-polling entry point for Fargate.
ENTRYPOINT ["python", "-m", "workers.main"]
