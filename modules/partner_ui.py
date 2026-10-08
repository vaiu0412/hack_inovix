"""Partner-side delivery steps: Accept -> Picked up -> Start -> Delivered (one button at a time, no skipping),
plus "Can't deliver", which opens Report with the delivery already filled in."""
import streamlit as st

from modules import assign, guards, partner_scope as scope, ui
from modules.report_ui import prefill

ICONS = {"accepted": ":material/thumb_up:", "picked_up": ":material/inventory_2:", "in_transit": ":material/play_arrow:",
         "delivered": ":material/check:"}
STAGE_STATE = {"assigned": "available", "accepted": "normal", "picked_up": "normal", "in_transit": "normal",
               "pending": "normal", "delayed": "delayed", "rescheduled": "delayed", "delivered": "done", "failed": "critical"}


def stage_pill(status):
    """'New' for work that was just assigned, then Accepted / Picked up / On the way / Delivered."""
    return ui.pill_html(STAGE_STATE.get(status, "off"), assign.STAGE.get(status, status))


def step_buttons(dp_id, branch, delivery, key):
    """The one next step for this delivery (+ a short note when delivering) and Can't deliver."""
    nxt = assign.NEXT.get(delivery["status"])
    if nxt is None:
        return
    note = ""
    if nxt == "delivered":
        note = st.text_input("Note", key=f"note_{key}", placeholder="Note (optional), e.g. left at gate",
                             label_visibility="collapsed")
    step, cant = st.columns(2)
    if step.button(assign.ACTION[nxt], type="primary", icon=ICONS[nxt], width="stretch", key=f"step_{key}"):
        try:
            scope.advance_delivery(dp_id, branch, delivery["delivery_id"], nxt, note)
            st.toast(f"{delivery['delivery_id']} · {assign.STAGE[nxt]}.", icon=ICONS[nxt])
        except (ValueError, PermissionError) as error:
            st.toast(str(error), icon=":material/error:")
        st.rerun()
    if cant.button("Can't deliver", icon=":material/block:", width="stretch", key=f"cant_{key}"):
        prefill(f"partner_{dp_id}", "customer", f"Can't deliver {delivery['delivery_id']} ({delivery['customer']}): ")
        st.switch_page(guards.PARTNER_PAGES["report"])
