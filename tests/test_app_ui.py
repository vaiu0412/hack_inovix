"""Click through the real app headlessly: sign-in, 3 roles, guards, OTP and the full demo loop."""
import re

import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1 import element_tree

from modules import auth, guards, store


def _indices(self):  # AppTest expects lists; single-choice segmented controls hold one value
    value = self.value
    values = [] if value is None else value if isinstance(value, (list, tuple)) else [value]
    return [self.options.index(self.format_func(v)) for v in values]


element_tree.ButtonGroup.indices = property(_indices)
DENIED = "**Access denied**"


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "ui.db"))
    store.init_db()


def ok(at):
    assert not at.exception, [e.value for e in at.exception]
    return at


def fresh(**session):
    at = AppTest.from_file("app.py", default_timeout=120)
    for key, value in session.items():
        at.session_state[key] = value
    return at


def start(view=None):
    return ok((fresh(login_view=view) if view else fresh()).run())


def continue_session(at):
    """Carry the signed-in session into a fresh AppTest (AppTest keeps stale widgets after st.rerun)."""
    return ok(fresh(**{k: at.session_state[k] for k in guards.SESSION_KEYS if k in at.session_state}).run())


def click(at, label, where=None):
    [button] = [b for b in (where or at).button if label in (b.label or "")][:1]
    button.click().run()
    return ok(at)


def sign_in(identifier, password, super_console=False):
    # the console is its own page at /console; run it directly, then carry the session into the app
    at = ok(AppTest.from_file("views/console.py", default_timeout=60).run()) if super_console else start()
    prefix = "sa" if super_console else "si"
    at.text_input(key=f"{prefix}_id").set_value(identifier)
    at.text_input(key=f"{prefix}_pw").set_value(password)
    click(at, "Sign in")
    return continue_session(at) if "authenticated" in at.session_state else at


def logout(at):
    at = continue_session(at)
    token = at.session_state["token"]
    click(at, "Sign out", at.sidebar)
    assert "authenticated" not in at.session_state and auth.validate_session(token) is None


def text_of(at):
    return " ".join(m.value for m in at.markdown)


def test_sign_in_page_shows_nothing_else(db):
    at = start()
    assert any(b.label == "Sign in" for b in at.button) and "Welcome back" in text_of(at)
    assert not at.metric and not at.dataframe and not list(at.sidebar.button)
    assert "Admin@123" not in text_of(at) and "Partner@123" not in text_of(at)   # no demo credentials
    visible = " ".join(m.value for m in at.markdown if not m.value.lstrip().startswith("<style>"))
    assert "Super Admin" not in visible and "console" not in visible.lower()     # console is not advertised
    [google] = [b for b in at.button if b.label == "Continue with Google"]
    assert google.disabled and google.help == "Google sign-in not set up"         # no fake Google flow


def test_sign_in_errors(db):
    assert sign_in("east.admin@deport.in", "wrong").error[0].value == "Wrong ID or password."
    assert sign_in("", "x").error[0].value == "Enter your email or ID."
    assert sign_in("superadmin@deport.in", "Super@123").error[0].value == "Wrong ID or password."  # console only
    assert sign_in("east.admin@deport.in", "Admin@123", super_console=True).error[0].value == "Super Admins only."


def test_super_admin_pages(db):
    at = sign_in("superadmin@deport.in", "Super@123", super_console=True)
    assert at.session_state["role"] == "super_admin"
    assert "Branches" in text_of(at) and "dp-kpi" in text_of(at)
    for page in guards.SUPER_PAGES.values():
        ok(at.switch_page(page).run())


def test_branch_admin_pages_are_scoped(db):
    at = sign_in("East.Admin@deport.in", "Admin@123")
    assert at.session_state["branch_id"] == "CBE-E" and "Coimbatore East" in text_of(at)
    assert "Partners active" in text_of(at) and "No alerts. All routes clear." in text_of(at)
    for page in guards.BRANCH_PAGES.values():
        ok(at.switch_page(page).run())
    at.switch_page(guards.BRANCH_PAGES["partners"]).run()
    team = set(at.dataframe[0].value["ID"])
    assert team == {"DP101", "DP102", "DP103", "DP106"}                    # DP104 (Priya) works in Central


def test_partner_pages(db):
    at = sign_in(" dp102 ", "Partner@123")
    assert at.session_state["dp_id"] == "DP102" and "Hi Karthik" in text_of(at)
    for page in guards.PARTNER_PAGES.values():
        ok(at.switch_page(page).run())
    at.switch_page(guards.PARTNER_PAGES["deliveries"]).run()
    assert "Ukkadam Wholesale Traders" in text_of(at) and "Lakshmi Boutique" not in text_of(at)


def _page_as(path, user):
    page = AppTest.from_file(path, default_timeout=60)
    if user:
        for key, value in dict(authenticated=True, user=user, role=user["role"], user_id=user["user_id"]).items():
            page.session_state[key] = value
    return page.run()


def test_guards_block_wrong_roles(db):
    karthik, boss = auth.get_user("DP102"), auth.get_user("superadmin")
    assert _page_as(guards.SUPER_PAGES["overview"], karthik).error[0].value.startswith(DENIED)
    assert _page_as(guards.BRANCH_PAGES["command"], karthik).error[0].value.startswith(DENIED)
    assert _page_as(guards.BRANCH_PAGES["disruptions"], boss).error[0].value.startswith(DENIED)
    assert _page_as(guards.PARTNER_PAGES["today"], None).error[0].value.startswith(DENIED)


def test_otp_login(db):
    at = start("otp")
    at.text_input(key="otp_id").set_value("dp102@deport.in")
    click(at, "Send code")
    code = at.session_state["otp_demo"]
    at = ok(fresh(login_view="otp", otp_step=2, otp_ident="dp102@deport.in", otp_demo=code).run())
    assert "DEMO" in " ".join(i.value for i in at.info)
    at.text_input(key="otp_code").set_value(code)
    click(at, "Sign in")
    assert at.session_state["dp_id"] == "DP102"


def test_branch_admin_adds_partner(db):
    # page run directly with the admin's session (AppTest doesn't submit forms on switch_page'd pages)
    page = AppTest.from_file(guards.BRANCH_PAGES["partners"], default_timeout=60)
    east = auth.get_user("east.admin")
    for key, value in dict(authenticated=True, user=east, role="branch_admin", user_id="east.admin").items():
        page.session_state[key] = value
    ok(page.run())
    page.text_input(key="ap_name_0").set_value("Ravi")
    page.text_input(key="ap_phone_0").set_value("+91 90000 20007")
    click(page, "Add partner")
    team = store.partners_df("CBE-E").set_index("partner_id")
    assert "DP107" in team.index and team.loc["DP107", "vehicle_id"] == "V9"
    shown = [c.value for c in page.code] + [m.value for m in page.markdown]  # success card + one-time password
    [temp] = sorted({t for v in shown for t in re.findall(r"Rpl-[a-z]{4}-[0-9]{3}", v or "")})
    ravi = sign_in("DP107", temp)
    assert ravi.session_state["dp_id"] == "DP107" and "No deliveries yet" in text_of(ravi)


def test_full_demo_flow(db):
    # DP102 reports the accident
    at = sign_in("DP102", "Partner@123")
    at.switch_page(guards.PARTNER_PAGES["report"]).run()
    at.text_area[0].set_value("avinasi rd la accident, full block, rendu mani neram aagum").run()
    click(at, "Check")
    assert "Accident · Avinashi Road" in text_of(at)
    click(at, "Send")
    [issue] = store.list_issues()
    assert issue["partner_id"] == "DP102" and issue["branch_id"] == "CBE-E" and issue["status"] == "analysed"
    logout(at)

    # Central's admin sees nothing; East's admin sees the critical alert and accepts
    assert "DP102 · Accident" not in text_of(sign_in("central.admin@deport.in", "Admin@123"))
    at = sign_in("east.admin@deport.in", "Admin@123")
    assert "DP102 · Accident · Avinashi Rd · 9 deliveries hit" in text_of(at)          # the alert banner
    ok(at.switch_page(guards.BRANCH_PAGES["disruptions"]).run())
    assert "What changed" in text_of(at) and "What to do" in text_of(at)
    click(at, "Accept plan")
    assert "Plan applied." in text_of(at)
    assert store.get_issue(issue["issue_id"])["status"] == "accepted"
    assert store.deliveries_df().set_index("delivery_id").loc["D06", "vehicle_id"] == "V6"   # same-branch backup
    logout(at)

    # DP102 sees the instruction; DP106 (backup van, same branch) has the new pickups
    at = sign_in("DP102", "Partner@123")
    assert "Route changed" in text_of(at) and "avoid Avinashi Road" in text_of(at)
    at = sign_in("DP106", "Partner@123")
    at.switch_page(guards.PARTNER_PAGES["deliveries"]).run()
    page = text_of(at)
    assert "KMCH Hospital" in page and "FreshMart Dairy" in page and "Ukkadam Wholesale" not in page
    assert store.list_issues(branch_id="CBE-S") == [] and store.list_issues(branch_id="CBE-C") == []


def test_every_page_renders_with_an_open_alert(db):
    """Each page of each role, while an alert is open (maps, Ripple Impact graph, 3 steps)."""
    from modules import partner_scope as scope

    seen = scope.preview_issue("DP102", "CBE-E", text="avinashi road accident, full block, 2 hours")
    scope.report_issue("DP102", "CBE-E", seen["problem"], transcript=seen["transcript"])
    for identifier, password, pages, console in (
            ("east.admin@deport.in", "Admin@123", guards.BRANCH_PAGES, False),
            ("DP102", "Partner@123", guards.PARTNER_PAGES, False),
            ("superadmin@deport.in", "Super@123", guards.SUPER_PAGES, True)):
        at = sign_in(identifier, password, super_console=console)
        for page in pages.values():
            ok(at.switch_page(page).run())


def test_assign_work_end_to_end(db):
    """Admin creates an order and assigns the best match; the partner sees New work and steps through it."""
    from modules import assign

    east = auth.get_user("east.admin")
    order_id, _ = assign.create_order(east, "Anand Stores", "+91 90000 30001", "Gandhipuram", "Parcel", "standard",
                                      "17:00", "small")
    page = _page_as(guards.BRANCH_PAGES["assign"], east)
    ok(page)
    assert f"{order_id} · Anand Stores" in text_of(page) and "km away" in text_of(page)
    click(page, "Assign best")
    vehicle = store.deliveries_df().set_index("delivery_id").loc[order_id, "vehicle_id"]
    dp = store.partners_df("CBE-E").set_index("vehicle_id").loc[vehicle, "partner_id"]

    page = _page_as(guards.BRANCH_PAGES["assign"], east)                  # new order through the form
    page.text_input[0].set_value("City Clinic")
    page.text_input[1].set_value("+91 90000 30002")
    page.text_input[2].set_value("rs puram")
    click(page, "Save order")
    assert "saved · RS Puram" in " ".join(s.value for s in page.success)
    assert len(assign.unassigned_orders("CBE-E")) == 1

    at = sign_in(dp, "Partner@123")
    assert "New work · 1" in text_of(at) and order_id in text_of(at)
    click(at, "Accept")
    assert store.deliveries_df().set_index("delivery_id").loc[order_id, "status"] == "accepted"
    at = continue_session(at)
    ok(at.switch_page(guards.PARTNER_PAGES["deliveries"]).run())          # every stop with its next step
    click(at, "Picked up")
    assert store.deliveries_df().set_index("delivery_id").loc[order_id, "status"] == "picked_up"
