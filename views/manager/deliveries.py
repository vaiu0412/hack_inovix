"""Deliveries: every order of the branch – filter, select a row for details; SMS sent to customers."""
from html import escape

import pandas as pd
import streamlit as st

from modules import assign, guards, manager_ui as mui, store, ui

guards.require_role("branch_admin")
ui.header("Deliveries")
ctx = mui.context()

deliveries = store.deliveries_df(branch_id=ctx["branch_id"])
risk = mui.risk_labels_now(ctx["open_issues"])
partner_of = dict(zip(ctx["partners"]["vehicle_id"], ctx["partners"]["partner_id"]))
state = deliveries.apply(lambda d: "done" if d["status"] == "delivered" else "unassigned" if d["status"] == "unassigned"
                         else ui.risk_state(risk.get(d["delivery_id"], "Low")), axis=1)
deliveries = deliveries.assign(state=state, partner=deliveries["vehicle_id"].map(partner_of).fillna("—"))

ui.restore_pref("del_state", ["normal", "delayed", "critical", "done", "unassigned"], multi=True)
ui.restore_pref("del_priority", ["medical", "perishable", "express", "standard"], multi=True)
ui.restore_pref("del_partner", [None] + sorted(set(partner_of.values())))
with st.container(horizontal=True, vertical_alignment="center", gap="small"):
    query = st.text_input("Search", placeholder="Customer, area, ID", label_visibility="collapsed",
                          icon=":material/search:", width=240)
    state_pick = st.pills("Status", ["normal", "delayed", "critical", "done", "unassigned"], selection_mode="multi",
                          format_func=ui.status_text, label_visibility="collapsed", key="del_state")
    priority_pick = st.pills("Priority", ["medical", "perishable", "express", "standard"], selection_mode="multi",
                             format_func=str.capitalize, label_visibility="collapsed", key="del_priority")
    partner_pick = st.selectbox("Partner", [None] + sorted(set(partner_of.values())), key="del_partner", width=180,
                                format_func=lambda p: "All partners" if p is None else f"{p} · {ctx['partner_names'][p]}",
                                label_visibility="collapsed")
view = deliveries
if query:
    hay = (view["customer"] + " " + view["address_area"] + " " + view["delivery_id"]).str.lower()
    view = view[hay.str.contains(query.lower(), regex=False)]
if state_pick:
    view = view[view["state"].isin(state_pick)]
if priority_pick:
    view = view[view["priority"].isin(priority_pick)]
if partner_pick:
    view = view[view["partner"] == partner_pick]

table = pd.DataFrame({"ID": view["delivery_id"], "Customer": view["customer"], "Area": view["address_area"],
                      "Priority": view["priority"].str.capitalize(), "Partner": view["partner"],
                      "Stage": view["status"].map(assign.STAGE).fillna(view["status"]),
                      "ETA": view["planned_eta"].fillna("—"), "Due": view["deadline"],
                      "Status": view["state"].map(ui.status_text), "Change": view["note"].fillna("").str.capitalize()})
table_col, panel_col = st.columns([2.2, 1], gap="medium")
with table_col:
    event = st.dataframe(table, hide_index=True, width="stretch", height=480, on_select="rerun",
                         selection_mode="single-row", key="deliveries_table")
    st.download_button("Download CSV", table.to_csv(index=False), "deport-deliveries.csv", "text/csv",
                       icon=":material/download:")
with panel_col, ui.card("delivery_panel"):
    rows = event.selection.rows if event else []
    if not rows:
        ui.empty_state("touch_app", "Select a delivery.")
    else:
        d = view.iloc[rows[0]]
        st.markdown(f"<p class='dp-h3'>{escape(d['customer'])}</p><p class='dp-small'>{escape(d['delivery_id'])} · "
                    f"{escape(d['address_area'])}</p><div style='margin:8px 0'>{ui.pill_html(d['state'])}</div>",
                    unsafe_allow_html=True)
        st.markdown(ui.kv([("Stage", escape(assign.STAGE.get(d["status"], d["status"]))),
                           ("Priority", escape(d["priority"].capitalize())), ("Partner", escape(d["partner"])),
                           ("Size", escape(str(d.get("package_size") or "small").capitalize())),
                           ("ETA", escape(d["planned_eta"] or "—")), ("Due", escape(d["deadline"])),
                           ("Change", escape(str(d["note"] or "—").capitalize()))]), unsafe_allow_html=True)
        st.link_button("Call customer", f"tel:{d['customer_phone']}", icon=":material/call:", width="stretch")
        mui.reassign_controls(ctx, d.to_dict())

sms = store.customer_messages(branch_id=ctx["branch_id"])
with st.expander(f"SMS sent ({len(sms)})", icon=":material/sms:"):
    if len(sms):
        st.dataframe(sms.rename(columns={"created_at": "Time", "issue_id": "Alert", "to_customer": "Customer",
                                         "to_phone": "Phone", "text": "Message"}), hide_index=True, width="stretch")
    else:
        st.caption("Sent when a plan is applied.")
