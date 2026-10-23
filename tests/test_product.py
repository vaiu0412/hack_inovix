"""Product features: photo reports, the public tracking link, customer messages (WhatsApp or draft), proof of
delivery, analytics and the Tamil partner UI. All without keys (Demo mode); providers are faked where needed."""
import json
import re
from pathlib import Path

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

from modules import analytics, auth, i18n, operations, pod, store
from modules import partner_scope as scope
from services import messaging, vision

PNG = b"\x89PNG\r\n\x1a\n" + bytes(64)
TAMIL = re.compile("[஀-௿]")


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("RIPPLE_DB", str(tmp_path / "product.db"))
    store.init_db()
    return store


def no_error(at):
    assert not at.exception, [e.value for e in at.exception]
    return at


# ---------------------------------------------------------------- photo reports
def test_photo_report_with_vision(db, monkeypatch):
    monkeypatch.setattr(vision, "analyse", lambda image, note="": {
        "type": "accident", "severity": "critical", "description": "Two cars blocking the road", "engine": "fake"})
    seen = scope.preview_issue("DP102", "CBE-E", photo=PNG)
    assert seen["problem"]["type"] == "accident" and seen["problem"]["severity"] == "critical"
    assert seen["problem"]["photo_note"] == "Two cars blocking the road"
    issue_id = scope.report_issue("DP102", "CBE-E", seen["problem"], photo=PNG)
    path = Path(store.get_issue(issue_id)["photo_path"])
    assert path.exists() and path.suffix == ".png" and path.read_bytes() == PNG


def test_photo_report_without_vision_needs_a_type(db):
    assert not vision.available()  # tests are offline: no vision model
    assert scope.preview_issue("DP102", "CBE-E", photo=PNG)["problem"] is None  # the partner picks a tile
    seen = scope.preview_issue("DP102", "CBE-E", photo=PNG, quick_type="breakdown")
    assert seen["problem"]["type"] == "breakdown" and seen["photo"] is None
    issue_id = scope.report_issue("DP102", "CBE-E", seen["problem"], quick_type="breakdown", photo=PNG)
    assert Path(store.get_issue(issue_id)["photo_path"]).exists()


# ---------------------------------------------------------------- tracking link
def test_every_delivery_has_a_private_tracking_code(db):
    codes = store.deliveries_df()["track_code"]
    assert codes.notna().all() and codes.is_unique and codes.str.len().min() >= 10
    assert store.delivery_by_code(store.track_code("D07"))["delivery_id"] == "D07"
    assert store.delivery_by_code("nope") is None and store.delivery_by_code("") is None
    assert operations.tracking_link("D07").endswith(f"/track?code={store.track_code('D07')}")


def test_tracking_page_shows_one_delivery_without_sign_in(db):
    page = AppTest.from_file("views/track.py", default_timeout=60)
    page.query_params["code"] = store.track_code("D01")
    text = " ".join(m.value for m in no_error(page.run()).markdown)
    assert "DELIVERY D01" in text and "Murugan" in text and "On the way" in text
    assert "+91" not in text and "D02" not in text  # no phone numbers, no other stops

    bad = AppTest.from_file("views/track.py", default_timeout=60)
    bad.query_params["code"] = "not-a-code"
    assert "This tracking link is not valid." in " ".join(m.value for m in no_error(bad.run()).markdown)


def test_tracking_link_skips_the_sign_in_page(db):
    app = AppTest.from_file("app.py", default_timeout=60)
    app.query_params["code"] = store.track_code("D01")
    no_error(app.run())
    assert any("DELIVERY D01" in m.value for m in app.markdown)
    assert not [b for b in app.button if b.label == "Sign in"] and "authenticated" not in app.session_state


# ---------------------------------------------------------------- customer messages
def test_messages_are_drafts_without_a_provider(db):
    assert messaging.provider() == "draft"
    assert messaging.send("+91 90000 10001", "Hi") == {"status": "draft", "provider": "draft"}
    assert messaging.label("draft", "draft") == "Draft (no provider)"


def test_twilio_whatsapp_send(monkeypatch):
    keys = {"TWILIO_ACCOUNT_SID": "AC123", "TWILIO_AUTH_TOKEN": "secret", "TWILIO_WHATSAPP_FROM": "whatsapp:+1415"}
    sent = {}

    class Reply:
        def raise_for_status(self):
            return None

    def fake_post(url, **kwargs):
        sent.update(url=url, **kwargs)
        return Reply()

    monkeypatch.setattr(messaging, "offline", lambda: False)
    monkeypatch.setattr(messaging, "setting", lambda name, default=None: keys.get(name, default))
    monkeypatch.setattr(messaging.httpx, "post", fake_post)
    assert messaging.provider() == "twilio_whatsapp"
    assert messaging.send("+91 90000 10001", "Running late") == {"status": "sent", "provider": "twilio_whatsapp"}
    assert "/Accounts/AC123/Messages.json" in sent["url"] and sent["data"]["To"] == "whatsapp:+919000010001"
    assert messaging.label("sent", "twilio_whatsapp") == "Sent · WhatsApp"


def test_plan_messages_carry_the_tracking_link(db):
    seen = scope.preview_issue("DP102", "CBE-E", text="avinasi rd la accident, full block, rendu mani neram aagum")
    issue_id = scope.report_issue("DP102", "CBE-E", seen["problem"], transcript=seen["transcript"])
    operations.accept(issue_id, "East Admin", branch_id="CBE-E")
    told = store.customer_messages(branch_id="CBE-E")
    assert len(told) and (told["status"] == "draft").all() and (told["provider"] == "draft").all()
    assert told["text"].str.contains("/track?code=", regex=False).all()


# ---------------------------------------------------------------- proof of delivery
def test_medical_order_needs_proof(db):
    with pytest.raises(ValueError, match="medical"):
        scope.mark_delivered("DP101", "CBE-E", "D06")  # KMCH insulin
    with pytest.raises(ValueError, match="photo"):
        pod.complete("DP101", "CBE-E", "D06", signature=PNG)
    with pytest.raises(ValueError, match="code or signature"):
        pod.complete("DP101", "CBE-E", "D06", photo=PNG)
    assert store.deliveries_df().set_index("delivery_id").loc["D06", "status"] == "in_transit"
    assert scope.mark_delivered("DP102", "CBE-E", "D07") is True  # other orders: proof optional


def test_proof_with_customer_code(db):
    result = pod.send_code("DP101", "CBE-E", "D06")
    code = result["demo_code"]
    assert result["status"] == "draft" and re.fullmatch(r"\d{4}", code)  # Demo mode: shown to the partner
    told = store.customer_messages()
    assert code not in " ".join(told["text"]) and list(told["status"]) == ["demo"]  # no clear text, not a draft
    wrong = "0000" if code != "0000" else "1111"
    with pytest.raises(ValueError, match="Wrong or expired"):
        pod.complete("DP101", "CBE-E", "D06", photo=PNG, code=wrong)
    assert pod.complete("DP101", "CBE-E", "D06", photo=PNG, code=code, note="Handed to the nurse")
    d = store.deliveries_df().set_index("delivery_id").loc["D06"]
    assert d["status"] == "delivered" and d["pod_method"] == "code" and Path(d["pod_photo_path"]).exists()
    assert "pod_code_hash" not in d and d["proof_note"] == "Handed to the nurse"   # never in what screens get
    with store.connect() as conn:
        assert conn.execute("SELECT pod_code_hash FROM deliveries WHERE delivery_id = 'D06'").fetchone()[0] is None


def test_code_locks_after_five_tries(db):
    code = pod.send_code("DP101", "CBE-E", "D06")["demo_code"]
    wrong = "0000" if code != "0000" else "1111"
    assert not any(pod.check_code("DP101", "CBE-E", "D06", wrong) for _ in range(pod.MAX_TRIES))
    assert pod.check_code("DP101", "CBE-E", "D06", code) is False  # locked, even with the right code


def test_proof_with_signature_and_scope(db):
    with pytest.raises(PermissionError):
        pod.send_code("DP102", "CBE-E", "D06")  # not Karthik's order
    assert pod.complete("DP104", "CBE-C", "D19", photo=PNG, signature=PNG)
    d = store.deliveries_df().set_index("delivery_id").loc["D19"]
    assert d["pod_method"] == "signature" and Path(d["pod_signature_path"]).exists()
    assert "proof recorded" in _track_text("D19")


def _track_text(delivery_id):
    page = AppTest.from_file("views/track.py", default_timeout=60)
    page.query_params["code"] = store.track_code(delivery_id)
    return " ".join(m.value for m in no_error(page.run()).markdown)


# ---------------------------------------------------------------- analytics
def test_history_summary_is_shipped():
    summary = analytics.history_summary()
    assert summary["synthetic"] is True and summary["rows"] > 10000
    grid = analytics.delay_matrix(summary)
    assert grid.shape[0] == 10 and grid.max().max() > 5  # 10 roads; rush hour is slow
    by_road, reliability = analytics.accuracy(summary)
    assert len(by_road) == 10 and reliability["n"].sum() == summary["accuracy"]["test_rows"]
    meta = json.loads((analytics.predict.MODEL_DIR / analytics.predict.META).read_text(encoding="utf-8"))
    assert summary["accuracy"]["mae_min"] == meta["metrics"]["mae_min"]  # same models, same test days


def test_live_partner_performance(db):
    scope.mark_delivered("DP102", "CBE-E", "D07")
    perf = analytics.partner_performance("CBE-E").set_index("partner_id")
    assert perf.loc["DP102", "delivered"] == 1 and perf.loc["DP102", "on_time"] == 1.0  # 09:00 demo clock
    assert perf.loc["DP101", "delivered"] == 0 and pd.isna(perf.loc["DP101", "on_time"])
    assert analytics.today_sla("CBE-E") == (1, 1) and analytics.today_sla("CBE-C") == (0, 0)


def test_disruption_heat_points(db):
    seen = scope.preview_issue("DP102", "CBE-E", text="avinasi rd la accident, full block, rendu mani neram aagum")
    issue_id = scope.report_issue("DP102", "CBE-E", seen["problem"], transcript=seen["transcript"])
    from modules.data_loader import load_all
    roads = load_all()["roads"]
    assert analytics.disruption_points("CBE-E", roads) == []
    operations.accept(issue_id, "East Admin", branch_id="CBE-E")
    [(lat, lng, weight)] = analytics.disruption_points("CBE-E", roads)
    assert 10.8 < lat < 11.2 and 76.8 < lng < 77.2 and 0 < weight <= 1
    assert analytics.disruption_points("CBE-C", roads) == []


# ---------------------------------------------------------------- Tamil + English
def test_language_files_match():
    en, ta = i18n.texts("en"), i18n.texts("ta")
    assert en.keys() == ta.keys() and len(en) > 100
    for key in en:
        assert set(re.findall(r"{(\w+)}", en[key])) == set(re.findall(r"{(\w+)}", ta[key])), key
        assert ta[key].strip(), key


def test_partner_app_in_tamil(db):
    store.set_prefs(auth.get_user("DP102")["user_id"], {"lang": "ta"})
    at = AppTest.from_file("app.py", default_timeout=120).run()
    at.text_input(key="si_id").set_value("DP102")
    at.text_input(key="si_pw").set_value("Partner@123")
    [button] = [b for b in at.button if b.label == "Sign in"]
    button.click().run()
    page = AppTest.from_file("app.py", default_timeout=120)
    for key in ("authenticated", "user", "role", "user_id", "token", "dp_id", "branch_id"):
        if key in at.session_state:
            page.session_state[key] = at.session_state[key]
    no_error(page.run())
    assert page.session_state["lang"] == "ta"
    text = " ".join(m.value for m in page.markdown if not m.value.lstrip().startswith("<style>"))
    assert TAMIL.search(text) and i18n.texts("ta")["hi"].split("{")[0].strip() in text
