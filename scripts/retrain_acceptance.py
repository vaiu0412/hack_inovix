"""Retrain the acceptance model (which recommendations admins take) from the decision log.

Nightly with cron, e.g.  0 2 * * *  cd /app && python scripts/retrain_acceptance.py
Uses the same database as the app (DB_PATH). The API also does this by itself once a day.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import learning, store  # noqa: E402

if __name__ == "__main__":
    store.init_db()
    print(json.dumps(learning.train(), indent=2))
