"""Shared test setup: no AI/network calls, and a fresh demo database per test module."""
import os

os.environ["RIPPLE_OFFLINE"] = "1"
os.environ["ESCALATION_SCHEDULER"] = "off"  # tests move offers along with a fake clock instead
# tests pick their own temporary database with RIPPLE_DB; never touch a real one set for the app
for name in ("DB_PATH", "DEPORT_DB"):
    os.environ.pop(name, None)
