"""Customer portal: the customer's email on an order (sign-in codes by email).

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade():
    """Add deliveries.customer_email."""
    op.add_column("deliveries", sa.Column("customer_email", sa.Text(), nullable=True))


def downgrade():
    """Remove it again."""
    op.drop_column("deliveries", "customer_email")
