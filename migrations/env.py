"""Alembic environment for PostgreSQL. The app runs it itself (modules/db.migrate) on start-up; by hand:

    DATABASE_URL=postgresql://user:pass@host:5432/deport alembic upgrade head

SQLite files are created and upgraded by modules/store.init_db() instead (no Alembic needed for the demo).
"""
import sys
from pathlib import Path

from alembic import context

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules import db, schema  # noqa: E402

target_metadata = schema.metadata


def run_migrations_offline():
    """Print the SQL instead of running it (alembic upgrade head --sql)."""
    context.configure(url=db._driver_url(db.url() or "postgresql://localhost/deport"),
                      target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connection = context.config.attributes.get("connection")
    if connection is not None:  # called from db.migrate() with the app's connection (right schema already)
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        return
    if not db.is_postgres():
        raise SystemExit("Set DATABASE_URL to a postgresql:// URL first.")
    with db.engine().connect() as conn:
        context.configure(connection=conn, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
        conn.commit()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
