"""AWS Lambda entry point (API Gateway HTTP API -> Mangum -> FastAPI).

Not deployed by the scaffold. In AWS, APP_ENV must not be local/test, which forces
AUTH_MODE=cognito and a non-memory repository backend (both TODO), so this handler will
refuse to start until those adapters exist. That is intentional.
"""

from __future__ import annotations

from mangum import Mangum

from api.main import create_app

handler = Mangum(create_app(), lifespan="off")
