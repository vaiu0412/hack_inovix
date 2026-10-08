"""Assign Work: new orders (one by one or CSV), the unassigned queue with a best match, auto-assign, workload."""
from datetime import time
from html import escape

import folium
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from modules import assign, guards, manager_ui as mui, ui

guards.require_role("branch_admin")
ui.header("Assign Work")
ctx = mui.context()
actor, branch = ctx["actor"], ctx["branch_id"]
queue = assign.unassigned_orders(branch)
done = st.session_state.pop("assign_msg", None)
if done:
    st.success(done, icon=":material/check_circle:")

tab_queue, tab_new, tab_csv, tab_load = st.tabs([f"Queue ({len(queue)})", "New order", "Upload CSV", "Workload"])

# ---------------------------------------------------------------- queue
with tab_queue:
    if queue.empty:
        with ui.card("queue_empty"):
            ui.empty_state("inventory_2", "No unassigned orders.")
    else:
        plan = st.session_state.get("auto_plan")
        if not plan and st.button(f"Auto-assign all ({len(queue)})", type="primary", icon=":material/auto_mode:",
                                  key="auto_all"):
            st.session_state["auto_plan"] = assign.auto_assign_plan(branch)
            st.rerun()
        if plan:
            with ui.card("auto_plan"):
                st.markdown("<p class='dp-h3'>Auto-assign plan</p><p class='dp-small'>Check, then confirm once.</p>",
                            unsafe_allow_html=True)
                st.dataframe(pd.DataFrame([{"Order": r["delivery_id"], "Customer": r["customer"], "Area": r["area"],
                                            "Partner": r["partner_id"] or "—", "Why": r["reason"]} for r in plan]),
                             hide_index=True, width="stretch")
                yes, no = st.columns(2)
                if yes.button("Confirm", type="primary", icon=":material/check:", width="stretch", key="auto_yes"):
                    count = assign.apply_plan(actor, plan)
                    st.session_state.pop("auto_plan", None)
                    st.session_state["assign_msg"] = f"{count} orders assigned."
                    st.rerun()
                if no.button("Cancel", width="stretch", key="auto_no"):
                    st.session_state.pop("auto_plan", None)
                    st.rerun()
        partners, deliveries = assign._partner_rows(branch)
        for order in queue.to_dict("records"):
            mui.order_card(ctx, order, assign.candidates(order, branch, partners=partners, deliveries=deliveries))

# ---------------------------------------------------------------- new order
with tab_new, ui.card("new_order"):
    form_round = st.session_state.get("new_order_round", 0)  # a new form key empties the fields after saving
    with st.form(f"new_order_form_{form_round}", border=False):
        c1, c2 = st.columns(2)
        customer = c1.text_input("Customer", placeholder="Anand Stores")
        phone = c2.text_input("Phone", placeholder="+91 90000 30001")
        area = st.text_input("Area", placeholder="Gandhipuram, RS Puram, KMCH …")
        c3, c4, c5 = st.columns(3)
        category = c3.selectbox("Category", assign.CATEGORIES)
        priority = c4.selectbox("Priority", assign.PRIORITIES, index=3, format_func=str.capitalize)
        deadline = c5.time_input("Deadline", value=time(17, 0), step=900)
        size = st.segmented_control("Size", assign.SIZES, default="small", format_func=str.capitalize)
        notes = st.text_area("Notes", placeholder="Optional", height=68)
        check_col, save_col = st.columns(2)
        check = check_col.form_submit_button("Check place", icon=":material/pin_drop:", width="stretch")
        save = save_col.form_submit_button("Save order", type="primary", icon=":material/add:", width="stretch")
    if check or save:
        problems, place = assign.check_order(customer, phone, area, category, priority, deadline.strftime("%H:%M"),
                                             size or "small")
        st.session_state["new_order_place"] = place
        if save and problems:
            st.error(" ".join(problems), icon=":material/error:")
        elif save:
            order_id, place = assign.create_order(actor, customer, phone, area, category, priority,
                                                  deadline.strftime("%H:%M"), size or "small", notes)
            # kept in session: the live refresh reruns the page right after a save
            st.session_state["assign_msg"] = f"{order_id} saved · {place['place']}. It is in the queue."
            st.session_state["new_order_round"] = form_round + 1
            st.rerun()
        elif not place:
            st.error("Place not found. Try another name.", icon=":material/location_off:")
    place = st.session_state.get("new_order_place")
    if place:
        st.markdown(f"{ui.pill_html('available', place['place'])} <span class='dp-small'>on "
                    f"{escape(place['road_name'])}</span>", unsafe_allow_html=True)
        pin = folium.Map(location=(place["lat"], place["lng"]), zoom_start=15, tiles=None, scrollWheelZoom=False)
        mui.add_basemap(pin)
        folium.Marker((place["lat"], place["lng"]), tooltip=place["place"]).add_to(pin)
        st_folium(pin, height=220, use_container_width=True, key="new_order_map", returned_objects=[])

# ---------------------------------------------------------------- CSV
with tab_csv, ui.card("csv"):
    st.download_button("Download template", assign.csv_template(), "deport-orders-template.csv", "text/csv",
                       icon=":material/download:")
    upload_round = st.session_state.get("csv_round", 0)
    upload = st.file_uploader("CSV file", type="csv", key=f"csv_{upload_round}")
    if upload is not None:
        try:
            rows = pd.read_csv(upload, dtype=str)
        except Exception:
            rows = None
            st.error("Can't read this file.", icon=":material/error:")
        if rows is not None:
            good, errors = assign.validate_rows(rows)
            st.markdown(f"{ui.pill_html('normal', f'{len(good)} ready')} "
                        f"{ui.pill_html('critical' if errors else 'off', f'{len(errors)} with errors')}",
                        unsafe_allow_html=True)
            if errors:
                st.dataframe(pd.DataFrame(errors, columns=["Row", "Problem"]), hide_index=True, width="stretch")
            if good and st.button(f"Import {len(good)} orders", type="primary", icon=":material/upload:",
                                  key="csv_import"):
                ids = assign.import_orders(actor, good)
                st.session_state["csv_round"] = upload_round + 1
                st.session_state["assign_msg"] = f"{len(ids)} orders imported."
                st.rerun()

# ---------------------------------------------------------------- workload
with tab_load, ui.card("workload"):
    load = assign.workload(branch)
    states = ctx["states"]
    load = load.assign(state=load["partner_id"].map(states).fillna("normal")).sort_values("open")
    colours = [ui.STATUS[s][2] for s in load["state"]]
    label = load["partner_id"] + " · " + load["name"]
    figure = go.Figure()
    figure.add_bar(y=label, x=load["limit"], orientation="h", marker=dict(color="rgba(148,163,184,.18)",
                   cornerradius=4), hoverinfo="skip", showlegend=False, width=0.6)
    figure.add_bar(y=label, x=load["open"], orientation="h", marker=dict(color=colours, cornerradius=4),
                   text=[f"{o}/{m}" for o, m in zip(load["open"], load["limit"])], textposition="outside",
                   customdata=load["state"].map(lambda s: ui.STATUS[s][0]),
                   hovertemplate="<b>%{y}</b><br>%{x} open stops · %{customdata}<extra></extra>", width=0.6,
                   showlegend=False)
    ui.style_figure(figure, height=60 + 48 * len(load))
    figure.update_layout(barmode="overlay", xaxis=dict(title=None, dtick=2), yaxis=dict(title=None))
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
    st.caption("Bar = open stops · grey = capacity · colour = status")
