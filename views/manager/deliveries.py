"""Deliveries: every order, its delivery partner, ETA, risk and what changed – plus customer messages."""
import streamlit as st

from modules import guards, manager_ui as mui, store, ui

guards.require_role("manager")
ui.header("Deliveries", "All of today's orders and the messages sent to customers.")
ui.live_updates()
ctx = mui.context()

deliveries = store.deliveries_df()
deliveries["risk"] = deliveries["delivery_id"].map(mui.risk_labels_now(ctx["open_issues"])).fillna("")
partners = ctx["partners"]
deliveries["driver"] = deliveries["vehicle_id"].map(dict(zip(partners["vehicle_id"], partners["name"])))
f1, f2 = st.columns([2, 3], vertical_alignment="bottom")
query = f1.text_input("Search deliveries", placeholder="Customer, area or ID", label_visibility="collapsed")
status_filter = f2.pills("Delivery status", ["pending", "delivered"], selection_mode="multi",
                         format_func=str.capitalize, label_visibility="collapsed")
view = deliveries
if query:
    hay = (view["customer"] + " " + view["address_area"] + " " + view["delivery_id"]).str.lower()
    view = view[hay.str.contains(query.lower(), regex=False)]
if status_filter:
    view = view[view["status"].isin(status_filter)]
columns = {"delivery_id": "ID", "customer": "Customer", "address_area": "Area", "priority": "Priority",
           "driver": "Delivery Partner", "vehicle_id": "Vehicle", "stop_order": "Stop", "planned_eta": "ETA",
           "deadline": "Due", "status": "Status", "risk": "Risk", "note": "Change", "customer_phone": "Phone"}
st.dataframe(view[list(columns)].rename(columns=columns)
             .style.map(lambda v: f"color: {ui.RISK_HEX.get(v, 'inherit')}; font-weight: 600", subset=["Risk"]),
             hide_index=True, width="stretch", height=460)
st.download_button("Download deliveries (CSV)", view[list(columns)].rename(columns=columns).to_csv(index=False),
                   "ripple-deliveries.csv", "text/csv", icon=":material/download:")

sms = store.customer_messages()
st.markdown(f"##### Customer messages ({len(sms)})")
if len(sms):
    st.dataframe(sms.rename(columns={"created_at": "Time", "issue_id": "Issue", "to_customer": "Customer",
                                     "to_phone": "Phone", "text": "Message"}), hide_index=True, width="stretch")
else:
    st.caption("Messages to customers appear here when a plan is accepted.")
