"""Partners: the team as a table (select a row for details) and Add partner."""
import streamlit as st

from modules import admin, guards, manager_ui as mui, ui
from modules.data_loader import load_all

guards.require_role("branch_admin")
ui.header("Partners")
ctx = mui.context()
mui.alert_banner(ctx)

table_col, panel_col = st.columns([2, 1], gap="medium")
with table_col:
    mui.team_table(ctx)
with panel_col:
    mui.partner_panel(ctx, st.session_state.get("selected_partner"))

# ---------------------------------------------------------------- add a partner (own branch only)
ui.section("Add partner", "person_add")
created = st.session_state.pop("new_partner", None)
if created:
    st.success(f"{created['dp_id']} added. Share this password once.", icon=":material/how_to_reg:")
    st.code(created["password"], language=None)
free = admin.free_vehicles(ctx["branch_id"])
with ui.card("add_partner"):
    if free.empty:
        ui.empty_state("no_transfer", "No free vehicle.")
    else:
        roads = load_all()["roads"]
        road_names = dict(zip(roads["road_id"], roads["name"]))
        form_round = st.session_state.get("add_partner_round", 0)  # a new key empties the form after each add


        def vehicle_label(vehicle_id):
            row = free.set_index("vehicle_id").loc[vehicle_id]
            return f"{ui.VEHICLE_EMOJI.get(row['type'], '')} {vehicle_id} · {row['reg_no']}"


        with st.form(f"add_partner_{form_round}", border=False):
            c1, c2, c3 = st.columns(3)
            name = c1.text_input("Name", key=f"ap_name_{form_round}")
            phone = c2.text_input("Phone", placeholder="+91 90000 20007", key=f"ap_phone_{form_round}")
            email = c3.text_input("Email", placeholder="Optional", key=f"ap_email_{form_round}")
            c4, c5 = st.columns([1, 2])
            vehicle = c4.selectbox("Vehicle", free["vehicle_id"].tolist(), format_func=vehicle_label)
            route = c5.multiselect("Route", list(road_names), format_func=road_names.get, placeholder="Roads in order")
            if st.form_submit_button("Add partner", type="primary", icon=":material/person_add:"):
                try:
                    dp_id, password = admin.add_partner(ctx["actor"], name, phone, email, vehicle, route)
                    st.session_state["new_partner"] = {"name": name, "dp_id": dp_id, "password": password}
                    st.session_state["add_partner_round"] = form_round + 1
                    st.rerun()
                except (ValueError, PermissionError) as error:
                    st.error(str(error))
