"""``python -m application.adapters.postgres``: apply pending schema migrations."""

import sys

from application.adapters.postgres.migrate import main

sys.exit(main())
