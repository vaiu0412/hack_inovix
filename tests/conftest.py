"""Shared test setup: no AI/network calls, and a fresh demo database per test module.

PostgreSQL: set TEST_DATABASE_URL (never DATABASE_URL – a real database is never used by the tests) and every test
gets its own empty schema, dropped afterwards. Tests marked sqlite_only (they edit the SQLite file directly) skip.
"""
import os
import tempfile
import uuid
from pathlib import Path

import pytest

os.environ["RIPPLE_OFFLINE"] = "1"
os.environ["ESCALATION_SCHEDULER"] = "off"  # tests move offers along with a fake clock instead
os.environ["LEARNING_SCHEDULER"] = "off"
os.environ["FEEDS_SCHEDULER"] = "off"
# tests pick their own temporary database with RIPPLE_DB; never touch a real one set for the app – and a test that
# doesn't set one gets a throwaway file, not the developer's data/deport.db
for name in ("DB_PATH", "DEPORT_DB", "DATABASE_URL", "DATABASE_SCHEMA"):
    os.environ.pop(name, None)
os.environ["RIPPLE_DB"] = str(Path(tempfile.mkdtemp(prefix="deport-tests-")) / "default.db")
if os.getenv("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    os.environ["DATABASE_SCHEMA"] = f"t_session_{uuid.uuid4().hex[:8]}"

from modules import db  # noqa: E402


def pytest_configure(config):
    config.addinivalue_line("markers", "sqlite_only: edits the SQLite file directly (skipped on PostgreSQL)")


def pytest_collection_modifyitems(config, items):
    if db.is_postgres():
        skip = pytest.mark.skip(reason="SQLite file test")
        for item in items:
            if "sqlite_only" in item.keywords:
                item.add_marker(skip)


@pytest.fixture(autouse=True)
def _postgres_schema():
    """On PostgreSQL every test starts in its own empty schema (like the SQLite tests' own temp file)."""
    if not db.is_postgres():
        yield
        return
    session_schema = os.environ["DATABASE_SCHEMA"]
    os.environ["DATABASE_SCHEMA"] = f"t_{uuid.uuid4().hex[:12]}"
    try:
        yield
    finally:
        db.dispose(drop_schema=True)
        os.environ["DATABASE_SCHEMA"] = session_schema


def pytest_sessionfinish(session, exitstatus):
    if db.is_postgres():
        db.dispose(drop_schema=True)
