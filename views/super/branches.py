"""Branches: switch branches on or off, add a branch."""
from html import escape

import streamlit as st

from modules import admin, guards, store, ui

actor = guards.require_permission("manage_branches")
ui.header("Branches", "Off = its people are signed out.")

summary = store.branch_summaries()
branches = store.branches_df().set_index("branch_id")
for b in summary.to_dict("records"):
    with ui.card(f"branch_{b['branch_id']}"):
        info, toggle = st.columns([5, 1.2], vertical_alignment="center")
        address = branches.loc[b["branch_id"], "address"] or ""
        info.markdown(f"<p class='dp-h3'>{escape(b['name'])}</p><p class='dp-small'>{b['branch_id']} · "
                      f"{escape(str(address))} · {escape(b['admin'])} · {b['partners']} partners</p>",
                      unsafe_allow_html=True)
        active = toggle.toggle("Active", value=b["is_active"], key=f"branch_active_{b['branch_id']}")
        if active != b["is_active"]:
            admin.set_branch_active(actor, b["branch_id"], active)
            st.toast(f"{b['name']} {'on' if active else 'off'}.")
            st.rerun()

ui.section("Add branch", "add_business")
with ui.card("add_branch"), st.form("create_branch", clear_on_submit=True, border=False):
    c1, c2 = st.columns(2)
    name = c1.text_input("Name", placeholder="Coimbatore West – Vadavalli")
    city = c2.text_input("City", value="Coimbatore")
    c3, c4 = st.columns(2)
    area = c3.text_input("Area", placeholder="Vadavalli")
    address = c4.text_input("Address", placeholder="Thondamuthur Road")
    if st.form_submit_button("Add branch", type="primary", icon=":material/add_business:"):
        try:
            branch_id = admin.create_branch(actor, name, city, area, address)
            st.success(f"{branch_id} added. Now add its admin.")
        except (ValueError, PermissionError) as error:
            st.error(str(error))
