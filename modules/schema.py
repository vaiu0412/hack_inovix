"""Every table, defined once with SQLAlchemy Core. No Streamlit, no I/O.

Used three ways:
- SQLite (default): store.init_db() creates missing tables from this (CREATE TABLE IF NOT EXISTS) and the old
  in-place upgrades in store add columns to older files;
- PostgreSQL: the Alembic migrations in migrations/ create and upgrade the same tables;
- tests check that a fresh SQLite file, a migrated PostgreSQL database and this file all agree.

Column order matters for a few INSERT … VALUES without a column list (vehicles), so keep it.
Text timestamps ('YYYY-MM-DD HH:MM:SS' or 'HH:MM:SS') are kept as text, as before; epoch seconds are floats.
"""
from sqlalchemy import Column, Float, ForeignKey, Index, Integer, LargeBinary, MetaData, Table, Text, text
from sqlalchemy.schema import CreateIndex, CreateTable

metadata = MetaData()


def _id(name="id"):
    return Column(name, Integer, primary_key=True, autoincrement=True)


def _table(name, *columns, autoincrement=False):
    return Table(name, metadata, *columns, sqlite_autoincrement=autoincrement)


def _default(value):
    return text(f"'{value}'") if isinstance(value, str) else text(str(value))


def _t(name, default=None, **kw):  # short helpers keep the table list readable
    return Column(name, Text, server_default=_default(default) if default is not None else None, **kw)


def _i(name, default=None, **kw):
    return Column(name, Integer, server_default=_default(default) if default is not None else None, **kw)


def _f(name, default=None, **kw):
    return Column(name, Float, server_default=_default(default) if default is not None else None, **kw)


branches = _table("branches", _t("branch_id", primary_key=True), _t("name", nullable=False), _t("city"), _t("area"),
                  _t("address"), _f("lat"), _f("lng"), _i("is_active", 1), _t("created_at"))
roles = _table("roles", _t("role_id", primary_key=True), _t("name", unique=True, nullable=False))
permissions = _table("permissions", _id("perm_id"), _t("code", unique=True, nullable=False), autoincrement=True)
role_permissions = _table("role_permissions", _t("role_id", primary_key=True),
                          Column("perm_id", Integer, primary_key=True, autoincrement=False))
partners = _table("partners", _t("partner_id", primary_key=True), _t("name"), _t("phone"), _t("vehicle_id"),
                  _t("shift_start"), _t("shift_end"), _t("languages"), _f("rating"), _t("status"), _t("branch_id"),
                  _i("experience_months", 0))
vehicles = _table("vehicles", _t("vehicle_id", primary_key=True), _t("reg_no"), _t("type"), _t("status"),
                  _f("current_lat"), _f("current_lng"), _t("route_roads"), _i("capacity"), _t("branch_id"))
deliveries = _table(
    "deliveries", _t("delivery_id", primary_key=True), _t("customer"), _t("address_area"), _f("lat"), _f("lng"),
    _t("vehicle_id"), _t("road_id"), _i("stop_order"), _t("planned_eta"), _t("deadline"), _t("priority"),
    _t("customer_phone"), _t("status", "in_transit"), _t("original_vehicle"), _t("note", ""), _t("branch_id"),
    _t("created_by"), _t("created_at"), _t("assigned_at"), _t("assigned_by"), _t("accepted_at"), _t("picked_at"),
    _t("delivered_at"), _t("package_size", "small"), _t("category"), _t("notes", ""), _t("proof_note", ""),
    _t("offer_status"), _t("offered_at"), _t("seen_at"), _i("escalation_level", 0), _t("track_code"), _t("pod_method"),
    _t("pod_at"), _t("pod_photo_path"), _t("pod_signature_path"), _t("pod_code_hash"), _f("pod_code_expires"),
    _i("pod_code_attempts", 0), _t("customer_email"))
assignment_history = _table("assignment_history", _id(), _t("delivery_id", nullable=False), _t("from_dp"),
                            _t("to_dp"), _t("by_user"), _t("reason"), _t("time"), _t("branch_id"), autoincrement=True)
issues = _table(
    "issues", _id("issue_id"), _t("created_at"), _t("partner_id"), _t("source"), _t("quick_type"), _t("text"),
    Column("audio", LargeBinary), _t("transcript"), _t("transcript_engine"), _t("problem"), _t("summary"), _t("status"),
    _t("plan"), _t("decided_at"), _t("decision_note"), _t("branch_id"), _t("audio_path"), _t("photo_path"),
    autoincrement=True)
disruptions = _table("disruptions", _id(), _i("issue_id"), _t("data"), _i("active", 1), _t("created_at"),
                     _t("branch_id"), autoincrement=True)
messages = _table("messages", _id(), _t("created_at"), _i("issue_id"), _t("to_partner"), _t("to_customer"),
                  _t("to_phone"), _t("channel"), _t("text"), _i("read", 0), _t("branch_id"), _t("status"),
                  _t("provider"),
                  _t("delivery_id"), autoincrement=True)
events = _table("events", _id(), _t("created_at"), _t("kind"), _t("text"), _i("issue_id"), _t("branch_id"),
                autoincrement=True)
meta = _table("meta", _t("key", primary_key=True), _t("value"))
users = _table(
    "users", _t("user_id", primary_key=True), _t("email", unique=True), _t("phone"), _t("display_name"),
    Column("role_id", Text, ForeignKey("roles.role_id"), nullable=False),
    Column("branch_id", Text, ForeignKey("branches.branch_id"), nullable=True),
    Column("dp_id", Text, ForeignKey("partners.partner_id"), nullable=True),
    _t("password_hash", nullable=False), _t("salt", nullable=False), _i("is_active", 1), _i("failed_attempts", 0),
    _f("locked_until", 0), _t("last_login"), _t("created_by"), _t("created_at"))
sessions = _table("sessions", _t("token_hash", primary_key=True), _t("user_id", nullable=False), _f("created_at"),
                  _f("expires_at"), _i("remember_me", 0), _i("revoked", 0))
otp_codes = _table("otp_codes", _id(), _t("user_id", nullable=False), _t("purpose", nullable=False),
                   _t("code_hash", nullable=False), _t("salt", nullable=False), _f("expires_at"), _i("used", 0),
                   _i("attempts", 0), _f("created_at"), autoincrement=True)
drafts = _table("drafts", _t("user_id", primary_key=True), _t("form", primary_key=True), _t("tile"), _t("text"),
                _t("transcript"), _t("audio_path"), _t("updated_at"))
user_prefs = _table("user_prefs", _t("user_id", primary_key=True), _t("key", primary_key=True), _t("value"),
                    _t("updated_at"))
route_geometry = _table("route_geometry", _t("key", primary_key=True), _t("points", nullable=False), _t("source"),
                        _t("meta"))
escalations = _table("escalations", _id(), _t("delivery_id", nullable=False), _t("dp_id"), _i("level"), _t("channel"),
                     _t("time"), _t("result"), _t("details"), _t("branch_id"), autoincrement=True)
settings = _table("settings", _t("key", primary_key=True), _t("value"), _t("updated_at"), _t("updated_by"))
location_log = _table("location_log", _id(), _t("time"), _t("branch_id"), _t("partner_id"), _t("vehicle_id"), _f("lat"),
                      _f("lng"), _f("accuracy_m"), _t("source"), autoincrement=True)
suggestions = _table("suggestions", _id(), _t("time"), _t("branch_id"), _t("kind"), _t("road_id"), _t("data"),
                     _t("status", "new"), _i("issue_id"), _t("decided_by"), _t("decided_at"), autoincrement=True)
decisions = _table("decisions", _id(), _t("time"), _t("branch_id"), _i("issue_id"), _t("decided_by"), _t("decision"),
                   _t("action_key"), _t("action_type"), _t("title"), _t("reason"), _t("features"), _f("p_accept"),
                   _t("source", "app"), autoincrement=True)
audit_log = _table("audit_log", _id(), _t("time"), _t("actor_user_id"), _t("action"), _t("target"), _t("details_json"),
                   _t("branch_id"), autoincrement=True)
# v12 – platform: phones registered for push, and the change feed behind the WebSockets
devices = _table("devices", _id(), _t("user_id", nullable=False), _t("dp_id"), _t("token", unique=True, nullable=False),
                 _t("platform"), _t("created_at"), _t("last_seen"), autoincrement=True)
changes = _table("changes", _id(), _t("time"), _t("branch_id"), _t("dp_id"), _t("kind"), _t("data"), autoincrement=True)

# lookups every screen and API call makes (branch scoping, a partner's work, an order's offer timeline)
Index("ix_deliveries_branch", deliveries.c.branch_id)
Index("ix_deliveries_vehicle", deliveries.c.vehicle_id)
Index("ix_deliveries_track_code", deliveries.c.track_code)
Index("ix_issues_branch_status", issues.c.branch_id, issues.c.status)
Index("ix_escalations_delivery", escalations.c.delivery_id)
Index("ix_messages_partner", messages.c.to_partner)
Index("ix_events_branch", events.c.branch_id)
Index("ix_location_log_partner", location_log.c.partner_id, location_log.c.time)
Index("ix_devices_dp", devices.c.dp_id)


def serial_key(table_name):
    """The auto-numbered primary key of a table (e.g. 'issue_id'), or None."""
    table = metadata.tables.get(table_name)
    if table is None:
        return None
    keys = list(table.primary_key.columns)
    return keys[0].name if len(keys) == 1 and keys[0].autoincrement is True else None


def primary_key(table_name):
    """The primary key column names of a table."""
    return [c.name for c in metadata.tables[table_name].primary_key.columns]


def sqlite_ddl():
    """CREATE TABLE IF NOT EXISTS … for every table, in SQLite's dialect (one script)."""
    from sqlalchemy.dialects import sqlite

    dialect = sqlite.dialect()
    return ";\n".join(str(CreateTable(t, if_not_exists=True).compile(dialect=dialect)).strip()
                      for t in metadata.sorted_tables) + ";"


def sqlite_index_ddl():
    """CREATE INDEX IF NOT EXISTS … for every index (run after older files got their columns)."""
    from sqlalchemy.dialects import sqlite

    dialect = sqlite.dialect()
    return ";\n".join(str(CreateIndex(i, if_not_exists=True).compile(dialect=dialect)).strip()
                      for t in metadata.sorted_tables for i in sorted(t.indexes, key=lambda i: i.name)) + ";"
