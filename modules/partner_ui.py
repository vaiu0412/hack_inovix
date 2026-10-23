"""Partner-side delivery steps: Accept -> Picked up -> Start -> Delivered (one button at a time, no skipping),
plus "Can't take" for a new offer (back to the admin) and "Can't deliver", which opens Report already filled in."""
import base64
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from modules import assign, escalation_ui, guards, pod, ui
from modules import partner_scope as scope
from modules.i18n import t
from modules.report_ui import prefill

ICONS = {
    "accepted": ":material/thumb_up:",
    "picked_up": ":material/inventory_2:",
    "in_transit": ":material/play_arrow:",
    "delivered": ":material/check:",
}
STAGE_STATE = {
    "assigned": "available",
    "accepted": "normal",
    "picked_up": "normal",
    "in_transit": "normal",
    "pending": "normal",
    "delayed": "delayed",
    "rescheduled": "delayed",
    "delivered": "done",
    "failed": "critical",
}


def stage_pill(status):
    """'New' for work that was just assigned, then Accepted / Picked up / On the way / Delivered."""
    return ui.pill_html(STAGE_STATE.get(status, "off"), t(f"stage_{status}"))


_signature = components.declare_component(
    "deport_signature", path=str(Path(__file__).resolve().parent.parent / "components" / "signature"))


def proof_form(dp_id, branch, delivery, key):
    """Medical: a photo + the customer's 4-digit code (sent to them) or their signature, then Delivered."""
    did = delivery["delivery_id"]
    st.caption(f":material/verified: {t('pod_title')} · {t('pod_rule')}")
    how = st.segmented_control(t("photo"), ["camera", "upload"], key=f"pod_how_{key}", format_func=t,
                               label_visibility="collapsed")
    shot = (st.camera_input(t("take_photo"), key=f"pod_cam_{key}") if how == "camera" else
            st.file_uploader(t("photo"), type=["jpg", "jpeg", "png", "webp"], key=f"pod_up_{key}")
            if how == "upload" else None)
    method = st.segmented_control(t("pod_title"), ["code", "signature"], key=f"pod_method_{key}",
                                  format_func=lambda m: t("pod_code") if m == "code" else t("pod_signature"),
                                  label_visibility="collapsed")
    code = signature = None
    if method == "code":
        send_col, code_col = st.columns(2, vertical_alignment="bottom")
        if send_col.button(t("pod_send_code"), icon=":material/sms:", width="stretch", key=f"pod_send_{key}"):
            st.session_state[f"pod_sent_{did}"] = pod.send_code(dp_id, branch, did)
        code = code_col.text_input(t("pod_enter_code"), max_chars=4, key=f"pod_code_{key}")
        sent = st.session_state.get(f"pod_sent_{did}")
        if sent:
            st.caption(t("pod_code_sent"))
            if sent.get("demo_code"):
                st.info(t("pod_demo_code", code=sent["demo_code"]), icon=":material/sms:")
    elif method == "signature":
        value = _signature(key=f"pod_sig_{key}", clear_label=t("clear"), use_label=t("use_signature"), default=None)
        if value:
            signature = base64.b64decode(value.split(",", 1)[1])
            st.caption(t("pod_signed"))
    note = st.text_input("Note", key=f"note_{key}", placeholder=t("note_placeholder"), label_visibility="collapsed")
    ready = bool(shot and ((method == "code" and code and len(code.strip()) == 4) or signature))
    if st.button(t("step_delivered"), type="primary", icon=ICONS["delivered"], width="stretch",
                 key=f"pod_done_{key}", disabled=not ready):
        try:
            pod.complete(dp_id, branch, did, photo=shot.getvalue(), signature=signature,
                         code=code if method == "code" else None, note=note)
            st.session_state.pop(f"pod_sent_{did}", None)
            st.toast(t("pod_done", id=did), icon=":material/verified:")
            st.rerun()
        except ValueError as error:
            st.error(t("pod_wrong_code") if "code" in str(error).lower() and method == "code" else str(error))


def step_buttons(dp_id, branch, delivery, key):
    """The one next step for this delivery (+ a short note when delivering) and Can't deliver.
    Medical orders get the proof-of-delivery form instead of a plain Delivered button."""
    nxt = assign.NEXT.get(delivery["status"])
    if nxt is None:
        return
    if nxt == "delivered" and pod.required(delivery.get("priority")):
        proof_form(dp_id, branch, delivery, key)
        return
    note = ""
    if nxt == "delivered":
        note = st.text_input("Note", key=f"note_{key}", placeholder=t("note_placeholder"),
                             label_visibility="collapsed")
    step, cant = st.columns(2)
    if step.button(t(f"step_{nxt}"), type="primary", icon=ICONS[nxt], width="stretch", key=f"step_{key}"):
        try:
            scope.advance_delivery(dp_id, branch, delivery["delivery_id"], nxt, note)
            st.toast(f"{delivery['delivery_id']} · {t(f'stage_{nxt}')}.", icon=ICONS[nxt])
        except (ValueError, PermissionError) as error:
            st.toast(str(error), icon=":material/error:")
        st.rerun()
    if delivery["status"] == "assigned":  # still an offer: hand it back with a reason
        with cant:
            escalation_ui.cant_take(dp_id, branch, delivery, key)
        return
    if cant.button(t("cant_deliver"), icon=":material/block:", width="stretch", key=f"cant_{key}"):
        prefill(f"partner_{dp_id}", "customer", f"Can't deliver {delivery['delivery_id']} ({delivery['customer']}): ")
        st.switch_page(guards.PARTNER_PAGES["report"])
