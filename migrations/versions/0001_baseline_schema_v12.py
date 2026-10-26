"""Baseline: every DEPORT table at schema v12 (the same tables modules/schema.py defines).

Revision ID: 0001
Revises: (none)
Create Date: 2026-10-23 20:23:38.620960
"""
import sqlalchemy as sa
from alembic import op

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """Create every table and index."""
    op.create_table('assignment_history',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('delivery_id', sa.Text(), nullable=False),
    sa.Column('from_dp', sa.Text(), nullable=True),
    sa.Column('to_dp', sa.Text(), nullable=True),
    sa.Column('by_user', sa.Text(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('time', sa.Text(), nullable=True),
    sa.Column('branch_id', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('time', sa.Text(), nullable=True),
    sa.Column('actor_user_id', sa.Text(), nullable=True),
    sa.Column('action', sa.Text(), nullable=True),
    sa.Column('target', sa.Text(), nullable=True),
    sa.Column('details_json', sa.Text(), nullable=True),
    sa.Column('branch_id', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    op.create_table('branches',
    sa.Column('branch_id', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.Column('city', sa.Text(), nullable=True),
    sa.Column('area', sa.Text(), nullable=True),
    sa.Column('address', sa.Text(), nullable=True),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lng', sa.Float(), nullable=True),
    sa.Column('is_active', sa.Integer(), server_default=sa.text('1'), nullable=True),
    sa.Column('created_at', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('branch_id'),
    sqlite_autoincrement=False
    )
    op.create_table('changes',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('time', sa.Text(), nullable=True),
    sa.Column('branch_id', sa.Text(), nullable=True),
    sa.Column('dp_id', sa.Text(), nullable=True),
    sa.Column('kind', sa.Text(), nullable=True),
    sa.Column('data', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    op.create_table('decisions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('time', sa.Text(), nullable=True),
    sa.Column('branch_id', sa.Text(), nullable=True),
    sa.Column('issue_id', sa.Integer(), nullable=True),
    sa.Column('decided_by', sa.Text(), nullable=True),
    sa.Column('decision', sa.Text(), nullable=True),
    sa.Column('action_key', sa.Text(), nullable=True),
    sa.Column('action_type', sa.Text(), nullable=True),
    sa.Column('title', sa.Text(), nullable=True),
    sa.Column('reason', sa.Text(), nullable=True),
    sa.Column('features', sa.Text(), nullable=True),
    sa.Column('p_accept', sa.Float(), nullable=True),
    sa.Column('source', sa.Text(), server_default=sa.text("'app'"), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    op.create_table('deliveries',
    sa.Column('delivery_id', sa.Text(), nullable=False),
    sa.Column('customer', sa.Text(), nullable=True),
    sa.Column('address_area', sa.Text(), nullable=True),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lng', sa.Float(), nullable=True),
    sa.Column('vehicle_id', sa.Text(), nullable=True),
    sa.Column('road_id', sa.Text(), nullable=True),
    sa.Column('stop_order', sa.Integer(), nullable=True),
    sa.Column('planned_eta', sa.Text(), nullable=True),
    sa.Column('deadline', sa.Text(), nullable=True),
    sa.Column('priority', sa.Text(), nullable=True),
    sa.Column('customer_phone', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'in_transit'"), nullable=True),
    sa.Column('original_vehicle', sa.Text(), nullable=True),
    sa.Column('note', sa.Text(), server_default=sa.text("''"), nullable=True),
    sa.Column('branch_id', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('created_at', sa.Text(), nullable=True),
    sa.Column('assigned_at', sa.Text(), nullable=True),
    sa.Column('assigned_by', sa.Text(), nullable=True),
    sa.Column('accepted_at', sa.Text(), nullable=True),
    sa.Column('picked_at', sa.Text(), nullable=True),
    sa.Column('delivered_at', sa.Text(), nullable=True),
    sa.Column('package_size', sa.Text(), server_default=sa.text("'small'"), nullable=True),
    sa.Column('category', sa.Text(), nullable=True),
    sa.Column('notes', sa.Text(), server_default=sa.text("''"), nullable=True),
    sa.Column('proof_note', sa.Text(), server_default=sa.text("''"), nullable=True),
    sa.Column('offer_status', sa.Text(), nullable=True),
    sa.Column('offered_at', sa.Text(), nullable=True),
    sa.Column('seen_at', sa.Text(), nullable=True),
    sa.Column('escalation_level', sa.Integer(), server_default=sa.text('0'), nullable=True),
    sa.Column('track_code', sa.Text(), nullable=True),
    sa.Column('pod_method', sa.Text(), nullable=True),
    sa.Column('pod_at', sa.Text(), nullable=True),
    sa.Column('pod_photo_path', sa.Text(), nullable=True),
    sa.Column('pod_signature_path', sa.Text(), nullable=True),
    sa.Column('pod_code_hash', sa.Text(), nullable=True),
    sa.Column('pod_code_expires', sa.Float(), nullable=True),
    sa.Column('pod_code_attempts', sa.Integer(), server_default=sa.text('0'), nullable=True),
    sa.PrimaryKeyConstraint('delivery_id'),
    sqlite_autoincrement=False
    )
    op.create_index('ix_deliveries_branch', 'deliveries', ['branch_id'], unique=False)
    op.create_index('ix_deliveries_track_code', 'deliveries', ['track_code'], unique=False)
    op.create_index('ix_deliveries_vehicle', 'deliveries', ['vehicle_id'], unique=False)
    op.create_table('devices',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Text(), nullable=False),
    sa.Column('dp_id', sa.Text(), nullable=True),
    sa.Column('token', sa.Text(), nullable=False),
    sa.Column('platform', sa.Text(), nullable=True),
    sa.Column('created_at', sa.Text(), nullable=True),
    sa.Column('last_seen', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token'),
    sqlite_autoincrement=True
    )
    op.create_index('ix_devices_dp', 'devices', ['dp_id'], unique=False)
    op.create_table('disruptions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('issue_id', sa.Integer(), nullable=True),
    sa.Column('data', sa.Text(), nullable=True),
    sa.Column('active', sa.Integer(), server_default=sa.text('1'), nullable=True),
    sa.Column('created_at', sa.Text(), nullable=True),
    sa.Column('branch_id', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    op.create_table('drafts',
    sa.Column('user_id', sa.Text(), nullable=False),
    sa.Column('form', sa.Text(), nullable=False),
    sa.Column('tile', sa.Text(), nullable=True),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('transcript', sa.Text(), nullable=True),
    sa.Column('audio_path', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('user_id', 'form'),
    sqlite_autoincrement=False
    )
    op.create_table('escalations',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('delivery_id', sa.Text(), nullable=False),
    sa.Column('dp_id', sa.Text(), nullable=True),
    sa.Column('level', sa.Integer(), nullable=True),
    sa.Column('channel', sa.Text(), nullable=True),
    sa.Column('time', sa.Text(), nullable=True),
    sa.Column('result', sa.Text(), nullable=True),
    sa.Column('details', sa.Text(), nullable=True),
    sa.Column('branch_id', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    op.create_index('ix_escalations_delivery', 'escalations', ['delivery_id'], unique=False)
    op.create_table('events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.Text(), nullable=True),
    sa.Column('kind', sa.Text(), nullable=True),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('issue_id', sa.Integer(), nullable=True),
    sa.Column('branch_id', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    op.create_index('ix_events_branch', 'events', ['branch_id'], unique=False)
    op.create_table('issues',
    sa.Column('issue_id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.Text(), nullable=True),
    sa.Column('partner_id', sa.Text(), nullable=True),
    sa.Column('source', sa.Text(), nullable=True),
    sa.Column('quick_type', sa.Text(), nullable=True),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('audio', sa.LargeBinary(), nullable=True),
    sa.Column('transcript', sa.Text(), nullable=True),
    sa.Column('transcript_engine', sa.Text(), nullable=True),
    sa.Column('problem', sa.Text(), nullable=True),
    sa.Column('summary', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=True),
    sa.Column('plan', sa.Text(), nullable=True),
    sa.Column('decided_at', sa.Text(), nullable=True),
    sa.Column('decision_note', sa.Text(), nullable=True),
    sa.Column('branch_id', sa.Text(), nullable=True),
    sa.Column('audio_path', sa.Text(), nullable=True),
    sa.Column('photo_path', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('issue_id'),
    sqlite_autoincrement=True
    )
    op.create_index('ix_issues_branch_status', 'issues', ['branch_id', 'status'], unique=False)
    op.create_table('location_log',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('time', sa.Text(), nullable=True),
    sa.Column('branch_id', sa.Text(), nullable=True),
    sa.Column('partner_id', sa.Text(), nullable=True),
    sa.Column('vehicle_id', sa.Text(), nullable=True),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lng', sa.Float(), nullable=True),
    sa.Column('accuracy_m', sa.Float(), nullable=True),
    sa.Column('source', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    op.create_index('ix_location_log_partner', 'location_log', ['partner_id', 'time'], unique=False)
    op.create_table('messages',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('created_at', sa.Text(), nullable=True),
    sa.Column('issue_id', sa.Integer(), nullable=True),
    sa.Column('to_partner', sa.Text(), nullable=True),
    sa.Column('to_customer', sa.Text(), nullable=True),
    sa.Column('to_phone', sa.Text(), nullable=True),
    sa.Column('channel', sa.Text(), nullable=True),
    sa.Column('text', sa.Text(), nullable=True),
    sa.Column('read', sa.Integer(), server_default=sa.text('0'), nullable=True),
    sa.Column('branch_id', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=True),
    sa.Column('provider', sa.Text(), nullable=True),
    sa.Column('delivery_id', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    op.create_index('ix_messages_partner', 'messages', ['to_partner'], unique=False)
    op.create_table('meta',
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('value', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('key'),
    sqlite_autoincrement=False
    )
    op.create_table('otp_codes',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.Text(), nullable=False),
    sa.Column('purpose', sa.Text(), nullable=False),
    sa.Column('code_hash', sa.Text(), nullable=False),
    sa.Column('salt', sa.Text(), nullable=False),
    sa.Column('expires_at', sa.Float(), nullable=True),
    sa.Column('used', sa.Integer(), server_default=sa.text('0'), nullable=True),
    sa.Column('attempts', sa.Integer(), server_default=sa.text('0'), nullable=True),
    sa.Column('created_at', sa.Float(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    op.create_table('partners',
    sa.Column('partner_id', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=True),
    sa.Column('phone', sa.Text(), nullable=True),
    sa.Column('vehicle_id', sa.Text(), nullable=True),
    sa.Column('shift_start', sa.Text(), nullable=True),
    sa.Column('shift_end', sa.Text(), nullable=True),
    sa.Column('languages', sa.Text(), nullable=True),
    sa.Column('rating', sa.Float(), nullable=True),
    sa.Column('status', sa.Text(), nullable=True),
    sa.Column('branch_id', sa.Text(), nullable=True),
    sa.Column('experience_months', sa.Integer(), server_default=sa.text('0'), nullable=True),
    sa.PrimaryKeyConstraint('partner_id'),
    sqlite_autoincrement=False
    )
    op.create_table('permissions',
    sa.Column('perm_id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('code', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('perm_id'),
    sa.UniqueConstraint('code'),
    sqlite_autoincrement=True
    )
    op.create_table('role_permissions',
    sa.Column('role_id', sa.Text(), nullable=False),
    sa.Column('perm_id', sa.Integer(), autoincrement=False, nullable=False),
    sa.PrimaryKeyConstraint('role_id', 'perm_id'),
    sqlite_autoincrement=False
    )
    op.create_table('roles',
    sa.Column('role_id', sa.Text(), nullable=False),
    sa.Column('name', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('role_id'),
    sa.UniqueConstraint('name'),
    sqlite_autoincrement=False
    )
    op.create_table('route_geometry',
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('points', sa.Text(), nullable=False),
    sa.Column('source', sa.Text(), nullable=True),
    sa.Column('meta', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('key'),
    sqlite_autoincrement=False
    )
    op.create_table('sessions',
    sa.Column('token_hash', sa.Text(), nullable=False),
    sa.Column('user_id', sa.Text(), nullable=False),
    sa.Column('created_at', sa.Float(), nullable=True),
    sa.Column('expires_at', sa.Float(), nullable=True),
    sa.Column('remember_me', sa.Integer(), server_default=sa.text('0'), nullable=True),
    sa.Column('revoked', sa.Integer(), server_default=sa.text('0'), nullable=True),
    sa.PrimaryKeyConstraint('token_hash'),
    sqlite_autoincrement=False
    )
    op.create_table('settings',
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('value', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.Text(), nullable=True),
    sa.Column('updated_by', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('key'),
    sqlite_autoincrement=False
    )
    op.create_table('suggestions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('time', sa.Text(), nullable=True),
    sa.Column('branch_id', sa.Text(), nullable=True),
    sa.Column('kind', sa.Text(), nullable=True),
    sa.Column('road_id', sa.Text(), nullable=True),
    sa.Column('data', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), server_default=sa.text("'new'"), nullable=True),
    sa.Column('issue_id', sa.Integer(), nullable=True),
    sa.Column('decided_by', sa.Text(), nullable=True),
    sa.Column('decided_at', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id'),
    sqlite_autoincrement=True
    )
    op.create_table('user_prefs',
    sa.Column('user_id', sa.Text(), nullable=False),
    sa.Column('key', sa.Text(), nullable=False),
    sa.Column('value', sa.Text(), nullable=True),
    sa.Column('updated_at', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('user_id', 'key'),
    sqlite_autoincrement=False
    )
    op.create_table('vehicles',
    sa.Column('vehicle_id', sa.Text(), nullable=False),
    sa.Column('reg_no', sa.Text(), nullable=True),
    sa.Column('type', sa.Text(), nullable=True),
    sa.Column('status', sa.Text(), nullable=True),
    sa.Column('current_lat', sa.Float(), nullable=True),
    sa.Column('current_lng', sa.Float(), nullable=True),
    sa.Column('route_roads', sa.Text(), nullable=True),
    sa.Column('capacity', sa.Integer(), nullable=True),
    sa.Column('branch_id', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('vehicle_id'),
    sqlite_autoincrement=False
    )
    op.create_table('users',
    sa.Column('user_id', sa.Text(), nullable=False),
    sa.Column('email', sa.Text(), nullable=True),
    sa.Column('phone', sa.Text(), nullable=True),
    sa.Column('display_name', sa.Text(), nullable=True),
    sa.Column('role_id', sa.Text(), nullable=False),
    sa.Column('branch_id', sa.Text(), nullable=True),
    sa.Column('dp_id', sa.Text(), nullable=True),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('salt', sa.Text(), nullable=False),
    sa.Column('is_active', sa.Integer(), server_default=sa.text('1'), nullable=True),
    sa.Column('failed_attempts', sa.Integer(), server_default=sa.text('0'), nullable=True),
    sa.Column('locked_until', sa.Float(), server_default=sa.text('0'), nullable=True),
    sa.Column('last_login', sa.Text(), nullable=True),
    sa.Column('created_by', sa.Text(), nullable=True),
    sa.Column('created_at', sa.Text(), nullable=True),
    sa.ForeignKeyConstraint(['branch_id'], ['branches.branch_id'], ),
    sa.ForeignKeyConstraint(['dp_id'], ['partners.partner_id'], ),
    sa.ForeignKeyConstraint(['role_id'], ['roles.role_id'], ),
    sa.PrimaryKeyConstraint('user_id'),
    sa.UniqueConstraint('email'),
    sqlite_autoincrement=False
    )


def downgrade():
    """Drop everything again."""
    op.drop_table('users')
    op.drop_table('vehicles')
    op.drop_table('user_prefs')
    op.drop_table('suggestions')
    op.drop_table('settings')
    op.drop_table('sessions')
    op.drop_table('route_geometry')
    op.drop_table('roles')
    op.drop_table('role_permissions')
    op.drop_table('permissions')
    op.drop_table('partners')
    op.drop_table('otp_codes')
    op.drop_table('meta')
    op.drop_index('ix_messages_partner', table_name='messages')
    op.drop_table('messages')
    op.drop_index('ix_location_log_partner', table_name='location_log')
    op.drop_table('location_log')
    op.drop_index('ix_issues_branch_status', table_name='issues')
    op.drop_table('issues')
    op.drop_index('ix_events_branch', table_name='events')
    op.drop_table('events')
    op.drop_index('ix_escalations_delivery', table_name='escalations')
    op.drop_table('escalations')
    op.drop_table('drafts')
    op.drop_table('disruptions')
    op.drop_index('ix_devices_dp', table_name='devices')
    op.drop_table('devices')
    op.drop_index('ix_deliveries_vehicle', table_name='deliveries')
    op.drop_index('ix_deliveries_track_code', table_name='deliveries')
    op.drop_index('ix_deliveries_branch', table_name='deliveries')
    op.drop_table('deliveries')
    op.drop_table('decisions')
    op.drop_table('changes')
    op.drop_table('branches')
    op.drop_table('audit_log')
    op.drop_table('assignment_history')
