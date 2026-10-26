"""Customer portal: my orders. Open orders show their live stage, ETA and (on the way) a map; delivered ones are
listed below. Only orders that carry this customer's mobile number or email – from any branch."""
from html import escape

import pandas as pd
import streamlit as st

from modules import customers, guards, operations, store, track_ui, ui

user = guards.require_role("customer")
ui.header("My orders", f"Hi {str(user['display_name']).split(' ')[0]}", live=False)


@st.fragment(run_every="30s")
def _orders():
    mine = customers.orders(user, track_url=operations.tracking_link)
    active = [o for o in mine if o["status"] not in customers.FINISHED]
    done = [o for o in mine if o["status"] in customers.FINISHED]
    if not mine:
        with ui.card("no_orders"):
            ui.empty_state("inventory_2", "No orders yet for this number or email.")
        return
    if not active:
        with ui.card("all_done"):
            ui.empty_state("task_alt", "Nothing on its way right now.")
    for i, order in enumerate(active):
        row = store.delivery_by_code(order["track_code"])
        if row is None:
            continue
        track_ui.status_card(row, key=f"c_{order['delivery_id']}", with_map=i == 0)  # map for the next one only
        st.markdown(f"<p class='dp-small'>From {escape(order['branch'] or 'DEPORT')} · share your tracking link:</p>",
                    unsafe_allow_html=True)
        st.code(order["track_url"], language=None, wrap_lines=True)
    if done:
        ui.section("Delivered", "task_alt")
        table = pd.DataFrame({
            "Order": [o["delivery_id"] for o in done],
            "Area": [o["area"] for o in done],
            "When": [(o["delivered_at"] or "")[:16] or "—" for o in done],
            "Status": [o["stage"] for o in done],
            "Proof": ["Yes" if o["proof"] else "—" for o in done],
        })
        st.dataframe(table, hide_index=True, width="stretch")
    st.caption("Updates every 30 s.")


_orders()
