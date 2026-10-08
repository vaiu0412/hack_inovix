"""Delivery Partners: the whole team as a spreadsheet, with details for the selected partner."""
import streamlit as st

from modules import admin, guards, manager_ui as mui, ui
from modules.data_loader import load_all

guards.require_role("branch_admin")
ui.header("Delivery Partners", "Search, filter, select a row for details, or download the list.")
ui.live_updates()
ctx = mui.context()

mui.team_table(ctx)
st.markdown("##### Selected delivery partner")
mui.partner_panel(ctx, st.session_state.get("selected_partner"))

# ---------------------------------------------------------------- add a delivery partner (own branch only)
st.markdown("##### Add delivery partner")
created = st.session_state.pop("new_partner", None)
if created:
    st.success(f"**{created['name']}** can sign in with partner ID **{created['dp_id']}** and this temporary "
               "password. It is shown only once – share it now:", icon=":material/how_to_reg:")
    st.code(created["password"], language=None)
free = admin.free_vehicles(ctx["branch_id"])
if free.empty:
    st.caption("All vehicles of this branch already have a delivery partner.")
else:
    roads = load_all()["roads"]
    road_names = dict(zip(roads["road_id"], roads["name"]))
    form_round = st.session_state.get("add_partner_round", 0)  # a new key empties the form after each add
    with st.form(f"add_partner_{form_round}"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Full name", key=f"ap_name_{form_round}")
        phone = c2.text_input("Phone", placeholder="+91 90000 20007", key=f"ap_phone_{form_round}")
        c3, c4 = st.columns(2)
        email = c3.text_input("Email (optional)", placeholder="name@ripple.in", key=f"ap_email_{form_round}")
        vehicle = c4.selectbox("Vehicle", free["vehicle_id"].tolist(), format_func=lambda v: (
            lambda r: f"{r['type'].title()} {r['reg_no']} ({v})")(free.set_index("vehicle_id").loc[v]))
        route = st.multiselect("Route (roads in driving order)", list(road_names), format_func=road_names.get)
        if st.form_submit_button("Add delivery partner", type="primary", icon=":material/person_add:"):
            try:
                dp_id, password = admin.add_partner(ctx["actor"], name, phone, email, vehicle, route)
                st.session_state["new_partner"] = {"name": name, "dp_id": dp_id, "password": password}
                st.session_state["add_partner_round"] = form_round + 1
                st.rerun()
            except (ValueError, PermissionError) as error:
                st.error(str(error))
