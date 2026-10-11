"""Shared test setup: no AI/network calls, and a fresh demo database per test module."""
import os
import tempfile
from pathlib import Path

os.environ["RIPPLE_OFFLINE"] = "1"
os.environ["ESCALATION_SCHEDULER"] = "off"  # tests move offers along with a fake clock instead
# tests pick their own temporary database with RIPPLE_DB; never touch a real one set for the app – and a test that
# doesn't set one gets a throwaway file, not the developer's data/deport.db
for name in ("DB_PATH", "DEPORT_DB"):
    os.environ.pop(name, None)
os.environ["RIPPLE_DB"] = str(Path(tempfile.mkdtemp(prefix="deport-tests-")) / "default.db")
