"""AWS Lambda entry point (API Gateway HTTP API -> Mangum -> FastAPI).

In AWS, APP_ENV is dev/prod, which forces AUTH_MODE=cognito, PostgreSQL (DATABASE_SECRET_ARN)
and the SQS/AppSync settings; the container refuses to start if any is missing.
"""

from __future__ import annotations

from mangum import Mangum

from api.main import app

# Reuse the module-level app: building a second one would open a second database pool.
handler = Mangum(app, lifespan="off")
