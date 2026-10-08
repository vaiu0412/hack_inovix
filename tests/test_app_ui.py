"""Click through the real app headlessly: login, role pages, data isolation and the full demo loop."""
import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1 import element_tree

from modules import guards, store


def _indices(self):  # AppTest expects lists; single-choice segmented controls hold one value
    value = self.value
    values = [] if value is None else value if isinstance(value, (list, tuple)) else [value]
    return [self.options.index(self.format_func(v)) for v in values]


element_tree.ButtonGroup.indices = property(_indices)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "ui.db"))
    store.init_db()


def ok(at):
    assert not at.exception, [e.value for e in at.exception]
    return at


def start():
    return ok(AppTest.from_file("app.py", default_timeout=120).run())


def login(at, role, user_id, password):
    """Sign in through the real form. On success, continue in a fresh AppTest holding that
    session (AppTest keeps stale login widgets after st.rerun, a browser does not)."""
    at.button_group(key="login_role").set_value([role]).run()
    at.text_input(key="login_user").set_value(user_id)
    at.text_input(key="login_password").set_value(password)
    [submit] = [b for b in at.button if b.label == "Sign in"]
    submit.click().run()
    ok(at)
    if "authenticated" not in at.session_state:
        return at  # login refused: stay on the home page
    session = {k: at.session_state[k] for k in guards.SESSION_KEYS}
    fresh = AppTest.from_file("app.py", default_timeout=120)
    for key, value in session.items():
        fresh.session_state[key] = value
    return ok(fresh.run())


def click(at, label, where=None):
    [button] = [b for b in (where or at).button if label in (b.label or "")][:1]
    button.click().run()
    return ok(at)


def logout(at):
    """Click Logout in a fresh AppTest holding the same session (avoids AppTest's stale widgets)."""
    fresh = AppTest.from_file("app.py", default_timeout=120)
    for key in guards.SESSION_KEYS:
        fresh.session_state[key] = at.session_state[key]
    at = ok(fresh.run())
    click(at, "Logout", at.sidebar)
    assert "authenticated" not in at.session_state
    assert any(b.label == "Sign in" for b in at.button)  # back on the home page
    return at


def text_of(at):
    return " ".join(m.value for m in at.markdown)


def test_home_shows_only_the_login(db):
    at = start()
    assert any(b.label == "Sign in" for b in at.button)
    assert not at.metric and not at.dataframe            # no KPIs, no tables before login
    assert "Welcome back" in text_of(at) and "DP101" not in text_of(at)
    assert not [b for b in at.sidebar.button]             # no sidebar content


def test_login_errors(db):
    at = start()
    [submit] = [b for b in at.button if b.label == "Sign in"]
    submit.click().run()
    assert at.error and "choose your role" in at.error[0].value
    login(at, "manager", "manager", "wrong")
    assert "Incorrect ID or password" in at.error[0].value
    login(at, "partner", "manager", "ripple@123")
    assert "belongs to a Manager" in at.error[0].value


def test_manager_sees_only_manager_pages(db):
    at = login(start(), "manager", "manager", "ripple@123")
    assert at.session_state["role"] == "manager"
    assert [m.label for m in at.metric][:2] == ["Partners on duty", "Deliveries today"]   # Command Center
    assert any(b.label == "Logout" for b in at.sidebar.button)
    for page in guards.MANAGER_PAGES.values():
        ok(at.switch_page(page).run())


def test_partner_sees_only_own_pages(db):
    at = login(start(), "partner", " dp102 ", "partner@123")
    assert at.session_state["dp_id"] == "DP102"
    assert "Hi Karthik" in text_of(at)
    for page in guards.PARTNER_PAGES.values():
        ok(at.switch_page(page).run())
    at.switch_page(guards.PARTNER_PAGES["deliveries"]).run()
    page = text_of(at)
    assert "Ukkadam Wholesale Traders" in page and "Lakshmi Boutique" not in page   # own stops only (DP101's)


def test_guard_blocks_wrong_role(db):
    page = AppTest.from_file(guards.MANAGER_PAGES["command"], default_timeout=60)
    for key, value in dict(authenticated=True, role="partner", user_id="DP102", display_name="Karthik",
                           dp_id="DP102").items():
        page.session_state[key] = value
    page.run()
    assert page.error and page.error[0].value == "Access denied" and not page.metric
    anonymous = AppTest.from_file(guards.PARTNER_PAGES["today"], default_timeout=60).run()
    assert anonymous.error and anonymous.error[0].value == "Access denied"


def test_full_demo_flow(db):
    # partner DP102 reports the accident
    at = login(start(), "partner", "DP102", "partner@123")
    at.switch_page(guards.PARTNER_PAGES["report"]).run()
    at.text_area[0].set_value("avinasi rd la accident, full block, rendu mani neram aagum").run()
    click(at, "Check")
    assert "Accident · Avinashi Road" in text_of(at)
    click(at, "Send to manager")
    [issue] = store.list_issues()
    assert issue["partner_id"] == "DP102" and issue["status"] == "analysed"
    logout(at)

    # manager sees the critical alert and accepts the plan
    at = login(start(), "manager", "manager", "ripple@123")
    assert "waiting for your decision" in text_of(at) and "Critical" in text_of(at)
    at.switch_page(guards.MANAGER_PAGES["disruptions"]).run()
    click(at, "Accept plan")
    assert store.get_issue(issue["issue_id"])["status"] == "accepted"
    logout(at)

    # DP102 sees the new instruction and the updated deliveries
    at = login(start(), "partner", "DP102", "partner@123")
    page = text_of(at)
    assert "New instructions" in page and "avoid Avinashi Road" in page
    at.switch_page(guards.PARTNER_PAGES["deliveries"]).run()
    assert "FreshMart Dairy" not in text_of(at)          # D10 moved to the backup van

    # backup partner DP106 has the new pickups – and nobody else's stops
    logout(at)
    at = login(start(), "partner", "DP106", "partner@123")
    assert "New instructions" in text_of(at)
    at.switch_page(guards.PARTNER_PAGES["deliveries"]).run()
    page = text_of(at)
    assert "FreshMart Dairy" in page and "KMCH Hospital" in page and "Ukkadam Wholesale" not in page
