"""Database connections for SQLite (default) or PostgreSQL – one small interface for the whole app. No Streamlit.

DATABASE_URL (environment or Streamlit secrets) picks the backend:
- unset, or sqlite:///path   -> a SQLite file (store.db_path(), or the path in the URL), Python's sqlite3 driver;
- postgresql://…             -> PostgreSQL through SQLAlchemy Core with psycopg 3, in schema DATABASE_SCHEMA
                                (default public); PostGIS is used for distance queries when it is installed.

The engine keeps writing plain SQL with ? placeholders. For PostgreSQL every statement is translated once (cached):
? -> %s, INSERT OR IGNORE -> ON CONFLICT DO NOTHING, INSERT OR REPLACE -> an upsert on the primary key,
RETURNING <key> so cursor.lastrowid works, PRAGMA / BEGIN IMMEDIATE skipped. Rows behave like sqlite3.Row:
row["col"], row[0], dict(row). Tables come from modules/schema.py; PostgreSQL is created and upgraded by Alembic
(migrations/), at most once per process.
"""
import os
import re
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path

from modules import schema

ROOT = Path(__file__).resolve().parent.parent
MIGRATIONS = ROOT / "migrations"
_SCHEMA_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
_lock = threading.Lock()
_engines = {}
_migrated = set()


# ---------------------------------------------------------------- configuration
def _secret(name):
    value = os.getenv(name)
    if not value:
        try:
            import streamlit as st

            value = st.secrets.get(name)
        except Exception:  # no secrets file / not running under Streamlit
            value = None
    return value if value and not str(value).startswith("paste-your") else None


def url():
    """DATABASE_URL, or None (= the SQLite file)."""
    return _secret("DATABASE_URL")


def is_postgres():
    """True when DATABASE_URL points at PostgreSQL."""
    return str(url() or "").startswith(("postgres://", "postgresql://", "postgresql+"))


def sqlite_file():
    """The file of a sqlite:///… DATABASE_URL, or None."""
    value = str(url() or "")
    return Path(value.split("sqlite:///", 1)[1]) if value.startswith("sqlite:///") else None


def schema_name():
    """The PostgreSQL schema the tables live in (DATABASE_SCHEMA, default public)."""
    name = (os.getenv("DATABASE_SCHEMA") or "public").strip().lower()
    if not _SCHEMA_NAME.match(name):
        raise ValueError("DATABASE_SCHEMA must be a plain name (letters, digits, _)")
    return name


def describe():
    """'SQLite' or 'PostgreSQL (+PostGIS)' – for the docs page and the health check."""
    if not is_postgres():
        return "SQLite"
    return "PostgreSQL + PostGIS" if has_postgis() else "PostgreSQL"


# ---------------------------------------------------------------- PostgreSQL engine
def _driver_url(value):
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://"):]
    if value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://"):]
    return value


def engine():
    """The SQLAlchemy engine for (DATABASE_URL, DATABASE_SCHEMA), made once per process."""
    from sqlalchemy import create_engine, text

    key = (url(), schema_name())
    with _lock:
        if key not in _engines:
            name = key[1]
            if name != "public":  # an own schema (e.g. one per test): make sure it exists first
                setup = create_engine(_driver_url(key[0]), poolclass=_null_pool())
                with setup.begin() as conn:
                    conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{name}"'))
                setup.dispose()
            _engines[key] = create_engine(_driver_url(key[0]), pool_pre_ping=True, pool_size=5, max_overflow=10,
                                          connect_args={"options": f"-c search_path={name},public"})
        return _engines[key]


def _null_pool():
    from sqlalchemy.pool import NullPool

    return NullPool


def dispose(drop_schema=False):
    """Close the engine for the current schema (tests: optionally drop that schema too)."""
    from sqlalchemy import text

    key = (url(), schema_name())
    with _lock:
        found = _engines.pop(key, None)
        _migrated.discard(key)
    if found is not None:
        found.dispose()
    if drop_schema and key[1] != "public" and key[0]:
        from sqlalchemy import create_engine

        setup = create_engine(_driver_url(key[0]), poolclass=_null_pool())
        with setup.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{key[1]}" CASCADE'))
        setup.dispose()


def migrate():
    """Create or upgrade the PostgreSQL tables with Alembic (once per process and schema; serialised across
    processes with an advisory lock, so the app and the API can start together)."""
    key = (url(), schema_name())
    if key in _migrated:
        return
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    with engine().connect() as conn:
        conn.execute(text("SELECT pg_advisory_lock(7310421)"))
        try:
            config = Config()
            config.set_main_option("script_location", str(MIGRATIONS))
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
            conn.commit()
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(7310421)"))
            conn.commit()
    _migrated.add(key)


@lru_cache(maxsize=8)
def _postgis(key):
    from sqlalchemy import text

    with engine().connect() as conn:
        return conn.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'postgis'")).first() is not None


def has_postgis():
    """True when the PostgreSQL database has the PostGIS extension."""
    return is_postgres() and _postgis((url(), schema_name()))


# ---------------------------------------------------------------- sqlite3-like connection for PostgreSQL
class Row(tuple):
    """A result row: row["column"], row[0] and dict(row), like sqlite3.Row."""

    def __new__(cls, values, keys):
        """Values plus column names (bytea comes back as bytes, like SQLite blobs)."""
        row = super().__new__(cls, [bytes(v) if isinstance(v, memoryview) else v for v in values])
        row._keys = keys
        return row

    def keys(self):
        """Column names."""
        return list(self._keys)

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._keys.index(key))
        return tuple.__getitem__(self, key)


class Cursor:
    """What conn.execute() returns: fetchone / fetchall / iteration, rowcount, lastrowid, description."""

    def __init__(self, result=None, returning=False):
        self.rowcount, self.lastrowid, self._rows, self._keys = -1, None, [], []
        if result is None:
            return
        self.rowcount = result.rowcount
        if result.returns_rows:
            self._keys = list(result.keys())
            self._rows = [Row(r, self._keys) for r in result.fetchall()]
        if returning:
            self.lastrowid = self._rows[0][0] if self._rows else None
            self._rows = []

    @property
    def description(self):
        """DB-API column descriptions (name first)."""
        return [(k, None, None, None, None, None, None) for k in self._keys] or None

    def fetchone(self):
        """The next row, or None."""
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        """All remaining rows."""
        rows, self._rows = self._rows, []
        return rows

    def __iter__(self):
        return iter(self.fetchall())


def _param(value):
    if isinstance(value, bool):
        return int(value)  # flags are INTEGER columns, as in SQLite
    if hasattr(value, "item") and not isinstance(value, (bytes, str)):
        return value.item()  # numpy numbers
    return value


class PgConnection:
    """A PostgreSQL connection that accepts the app's SQLite-style SQL."""

    backend = "postgresql"

    def __init__(self):
        self.sa = engine().connect()

    def execute(self, sql, params=()):
        """Run one SQLite-style statement."""
        statement, returning = translate(sql)
        if statement is None:
            return Cursor()
        result = self.sa.exec_driver_sql(statement, tuple(_param(p) for p in params))
        return Cursor(result, returning)

    def executemany(self, sql, seq):
        """Run one statement for many parameter rows."""
        statement, returning = translate(sql, many=True)
        rows = [tuple(_param(p) for p in row) for row in seq]
        if statement is None or not rows:
            return Cursor()
        return Cursor(self.sa.exec_driver_sql(statement, rows))

    def executescript(self, script):
        """Not used for PostgreSQL."""
        raise NotImplementedError("PostgreSQL tables come from Alembic migrations (modules/db.migrate)")

    def commit(self):
        """Commit the transaction."""
        self.sa.commit()

    def rollback(self):
        """Roll the transaction back."""
        self.sa.rollback()

    def close(self):
        """Give the connection back to the pool."""
        self.sa.close()


def connect_postgres():
    """A new PostgreSQL connection (the caller commits/rolls back and closes – store.connect() does)."""
    return PgConnection()


# ---------------------------------------------------------------- SQL translation (SQLite -> PostgreSQL)
_INSERT = re.compile(r"^\s*INSERT\s+(OR\s+(IGNORE|REPLACE)\s+)?INTO\s+(\w+)\s*(\(([^)]*)\))?", re.I)
_SKIP = re.compile(r"^\s*(PRAGMA|BEGIN(\s+IMMEDIATE|\s+DEFERRED|\s+EXCLUSIVE)?\s*$)", re.I)


def _placeholders(sql):
    """? -> %s outside string literals; every % doubled (psycopg reads % everywhere, even inside quotes)."""
    out, quoted = [], False
    for ch in sql:
        if ch == "'":
            quoted = not quoted
        if ch == "%":
            out.append("%%")
        elif ch == "?" and not quoted:
            out.append("%s")
        else:
            out.append(ch)
    return "".join(out)


@lru_cache(maxsize=2048)
def translate(sql, many=False):
    """(PostgreSQL statement or None to skip, whether RETURNING <key> was added for lastrowid)."""
    if _SKIP.match(sql):
        return None, False
    statement = re.sub(r"\bIFNULL\(", "COALESCE(", sql, flags=re.I)
    returning = False
    found = _INSERT.match(statement)
    if found:
        mode, table, columns = (found.group(2) or "").upper(), found.group(3), found.group(5)
        statement = statement[:found.start(1)] + statement[found.end(1):] if found.group(1) else statement
        if mode == "IGNORE":
            statement = statement.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        elif mode == "REPLACE":
            keys = schema.primary_key(table)
            names = [c.strip() for c in columns.split(",")] if columns else \
                [c.name for c in schema.metadata.tables[table].columns]
            updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in names if c not in keys)
            statement = statement.rstrip().rstrip(";") + f" ON CONFLICT ({', '.join(keys)}) " + \
                (f"DO UPDATE SET {updates}" if updates else "DO NOTHING")
        key = schema.serial_key(table)
        if key and not many and " RETURNING " not in statement.upper():
            statement = statement.rstrip().rstrip(";") + f" RETURNING {key}"
            returning = True
    return _placeholders(statement), returning


# ---------------------------------------------------------------- errors
def errors():
    """Exception types a failed query raises on either backend."""
    try:
        from sqlalchemy.exc import DBAPIError

        return (sqlite3.Error, DBAPIError)
    except ImportError:
        return (sqlite3.Error,)
