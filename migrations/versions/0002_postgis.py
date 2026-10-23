"""PostGIS for distance queries (nearest vehicle): the extension and a geography index on vehicle positions.

Optional: on a server without PostGIS (or without the right to install it) nothing happens and the app measures
distances in Python instead (modules/store.nearest_vehicles).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-23
"""
import sqlalchemy as sa
from alembic import op

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None

GEO = ("(ST_SetSRID(ST_MakePoint(current_lng, current_lat), 4326)::geography)")


def upgrade():
    """Install PostGIS when the server offers it, then index vehicle positions."""
    conn = op.get_bind()
    offered = conn.execute(sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'postgis'")).first()
    if not offered:
        return
    savepoint = conn.begin_nested()  # no rights to install it: roll back just this step, keep going
    try:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis WITH SCHEMA public"))
        savepoint.commit()
    except sa.exc.DBAPIError:
        savepoint.rollback()
        return
    op.execute(f"CREATE INDEX IF NOT EXISTS ix_vehicles_geo ON vehicles USING GIST ({GEO})")


def downgrade():
    """Drop the index (the extension stays: other schemas may use it)."""
    op.execute("DROP INDEX IF EXISTS ix_vehicles_geo")
