"""Shared test setup: no AI/network calls, and a fresh demo database per test module."""
import os

os.environ["RIPPLE_OFFLINE"] = "1"
