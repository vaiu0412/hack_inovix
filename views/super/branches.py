"""Branches: list, create, activate / deactivate."""
from html import escape

import streamlit as st

from modules import admin, guards, store, ui

actor = guards.require_permission("manage_branches")
ui.header("Branches", "Create branches and switch them on or off. Deactivating a branch signs its people out.")

summary = store.branch_summaries()
branches = store.branches_df().set_index("branch_id")
for b in summary.to_dict("records"):
    with st.container(border=True):
        info, toggle = st.columns([5, 1.2], vertical_alignment="center")
        detail = branches.loc[b["branch_id"]]
        info.markdown(f"**{escape(b['name'])}** · {b['branch_id']}<br><small>{escape(str(detail['address'] or ''))} · "
                      f"admin {escape(b['admin'])} · {b['partners']} partners · {b['deliveries']} deliveries today"
                      f"</small>", unsafe_allow_html=True)
        active = toggle.toggle("Active", value=b["is_active"], key=f"branch_active_{b['branch_id']}")
        if active != b["is_active"]:
            admin.set_branch_active(actor, b["branch_id"], active)
            st.toast(f"{b['name']} {'activated' if active else 'deactivated'}")
            st.rerun()

st.markdown("##### Create branch")
with st.form("create_branch", clear_on_submit=True):
    c1, c2 = st.columns(2)
    name = c1.text_input("Branch name", placeholder="Coimbatore West – Vadavalli")
    city = c2.text_input("City", value="Coimbatore")
    c3, c4 = st.columns(2)
    area = c3.text_input("Area", placeholder="Vadavalli")
    address = c4.text_input("Address", placeholder="Thondamuthur Road, Vadavalli")
    if st.form_submit_button("Create branch", type="primary", icon=":material/add_business:"):
        try:
            branch_id = admin.create_branch(actor, name, city, area, address)
            st.success(f"Branch **{name}** created ({branch_id}). Add its branch admin under Branch Admins.")
        except (ValueError, PermissionError) as error:
            st.error(str(error))
