"""Click through both screens headlessly: partner reports -> manager accepts -> backup partner updated."""
import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1 import element_tree

from modules import store


def _indices(self):  # AppTest expects lists; single-choice segmented controls hold one value
    value = self.value
    values = [] if value is None else value if isinstance(value, (list, tuple)) else [value]
    return [self.options.index(self.format_func(v)) for v in values]


element_tree.ButtonGroup.indices = property(_indices)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "ui.db"))
    store.init_db()


def open_page(page, query=None, state=None):
    at = AppTest.from_file("app.py", default_timeout=120)
    at.query_params.update(query or {})
    for key, value in (state or {}).items():
        at.session_state[key] = value
    at.switch_page(page)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def click(at, label):
    [button] = [b for b in at.button if label in (b.label or "")][:1]
    button.click().run()
    assert not at.exception, [e.value for e in at.exception]
    return at


def test_every_screen_renders(db):
    open_page("views/home.py")
    for section in ["Live map", "Issues", "Deliveries", "Activity"]:
        open_page("views/manager.py", state={"section": section})
    open_page("views/partner.py")                       # "who's driving today?"
    open_page("views/partner.py", query={"id": "P1"})


def test_report_accept_loop(db):
    at = open_page("views/partner.py", query={"id": "P1"})
    click(at, "Report a problem")
    at.text_area[0].set_value("avinasi rd la accident, full block, rendu mani neram").run()
    click(at, "Check")
    assert any("Accident · Avinashi Road" in m.value for m in at.markdown)
    click(at, "Send to manager")
    [issue] = store.list_issues()
    assert issue["status"] == "analysed"

    at = open_page("views/manager.py", state={"section": "Issues"})
    click(at, "Accept plan")
    assert store.get_issue(issue["issue_id"])["status"] == "accepted"

    at = open_page("views/partner.py", query={"id": "P6"})  # backup partner Lakshmi
    assert any("From operations" in m.value for m in at.markdown)
    click(at, "Delivered")
    assert store.get_partner("P6")["delivered"] == 1
