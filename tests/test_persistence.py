"""Data is never lost: sign-out, page reloads and app restarts keep everything; only an explicit,
backed-up reset clears demo data."""
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from modules import admin, auth, partner_scope as scope, store

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "deport.db"))
    store.init_db()
    return tmp_path / "deport.db"


def resets():
    return int(store.audit_df(1000)["action"].eq("reset_demo").sum())


def restart_and_read(db_file):
    """A brand-new Python process (= the Streamlit app restarted) opens the same file and reads it."""
    code = ("import json; from modules import store; store.init_db(); "
            "print(json.dumps({'issues': len(store.list_issues()), "
            "'d07': store.deliveries_df().set_index('delivery_id').loc['D07', 'status'], "
            "'partners': sorted(store.partners_df()['partner_id']), "
            "'draft': store.get_draft('DP102', 'partner_DP102'), 'prefs': store.get_prefs('east.admin'), "
            "'resets': int(store.audit_df(1000)['action'].eq('reset_demo').sum())}))")
    env = {**os.environ, "RIPPLE_DB": str(db_file), "RIPPLE_OFFLINE": "1"}
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_data_survives_sign_out_and_restart(db):
    # write: an issue report, a delivery, a new partner, a draft and saved filters
    seen = scope.preview_issue("DP102", "CBE-E", text="avinashi road accident, full block")
    scope.report_issue("DP102", "CBE-E", seen["problem"], transcript=seen["transcript"])
    scope.mark_delivered("DP102", "CBE-E", "D07")
    east, _ = auth.authenticate("east.admin@deport.in", "Admin@123")
    dp_id, _ = admin.add_partner(east, "Ravi", "+91 90000 20007", "", "V9", ["R1"])
    store.save_draft("DP102", "partner_DP102", tile="flood", text="water near Sungam")
    store.set_prefs("east.admin", {"last_page": "map_ops", "team_status": ["critical"]})

    # sign out = revoke the session only
    token = auth.create_session("DP102")
    auth.revoke_session(token)
    assert auth.validate_session(token) is None

    after = restart_and_read(db)
    assert after["issues"] == 1 and after["d07"] == "delivered" and dp_id in after["partners"]
    assert after["draft"]["text"] == "water near Sungam" and after["prefs"]["last_page"] == "map_ops"
    assert after["resets"] == 1                                    # only the first-run seed, never again


def test_startup_never_reseeds(db):
    store.update_delivery("D01", status="delivered")
    for _ in range(3):
        store.init_db()  # every page load calls this
    assert store.deliveries_df().set_index("delivery_id").loc["D01", "status"] == "delivered"
    assert resets() == 1


def test_reset_is_explicit_and_backed_up_first(db):
    seen = scope.preview_issue("DP102", "CBE-E", text="trichy road flood")
    scope.report_issue("DP102", "CBE-E", seen["problem"], transcript=seen["transcript"])
    saved = store.reset_demo()
    assert store.list_issues() == []                                # the demo is back to 09:00 ...
    assert saved.parent.name == "backups" and saved.exists()        # ... but nothing is really lost
    with sqlite3.connect(saved) as copy:
        assert copy.execute("SELECT COUNT(*) FROM issues").fetchone()[0] == 1


def test_voice_notes_are_files_and_drafts_persist(db):
    issue_id = store.add_issue("DP102", text="", audio=b"RIFF-demo-wave", branch_id="CBE-E")
    path = Path(store.get_issue(issue_id)["audio_path"])
    assert path.parent.name == "voice" and path.read_bytes() == b"RIFF-demo-wave"
    store.save_draft("DP103", "partner_DP103", tile="accident", text="", audio_path=str(path))
    assert store.get_draft("DP103", "partner_DP103")["audio_path"] == str(path)
    store.clear_draft("DP103", "partner_DP103")
    assert store.get_draft("DP103", "partner_DP103") is None


def test_database_settings(db):
    with store.connect() as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert store.db_path() == db


def test_old_ripple_database_is_adopted_not_lost(tmp_path):
    old, new = tmp_path / "ripple.db", tmp_path / "deport.db"
    with sqlite3.connect(old) as conn:
        conn.execute("CREATE TABLE notes (text TEXT)")
        conn.execute("INSERT INTO notes VALUES ('keep me')")
    store.adopt_old_db(old, new)
    with sqlite3.connect(new) as conn:
        assert conn.execute("SELECT text FROM notes").fetchone()[0] == "keep me"
    assert old.exists()


def test_default_database_is_an_absolute_project_path(monkeypatch):
    monkeypatch.delenv("RIPPLE_DB", raising=False)
    monkeypatch.delenv("DEPORT_DB", raising=False)
    assert store.DEFAULT_DB.is_absolute() and store.DEFAULT_DB == ROOT / "data" / "deport.db"


def test_prototype_database_is_backed_up_and_gets_accounts(db):
    """The first prototype stored partners P1-P6 and had no accounts; the live site kept that file."""
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM users")
        conn.execute("UPDATE partners SET partner_id = 'P' || substr(partner_id, 5)")
    store.init_db()
    assert auth.authenticate("superadmin@deport.in", "Super@123", "super")[0]["user_id"] == "superadmin"
    assert auth.authenticate("DP102", "Partner@123")[0]["dp_id"] == "DP102"
    assert any(p.name.endswith("before-reset.db") for p in store.files_dir("backups").iterdir())


def test_data_without_accounts_gets_demo_accounts_and_keeps_data(db):
    store.update_delivery("D01", status="delivered")
    with sqlite3.connect(db) as conn:
        conn.execute("DELETE FROM users")
    store.init_db()
    assert auth.authenticate("east.admin@deport.in", "Admin@123")[0]["branch_id"] == "CBE-E"
    assert store.deliveries_df().set_index("delivery_id").loc["D01", "status"] == "delivered"   # data kept
    assert resets() == 1
