"""Landing page: pick a role."""
import streamlit as st

from modules import operations, ui

ui.header("Ripple", "Delivery operations that react when the road changes.", live=False)

k = operations.kpis()
left, right = st.columns(2, gap="medium")
with left, st.container(border=True):
    st.markdown("#### :material/monitoring: Operations")
    st.write("For managers. See every partner on the map, tap anyone for their deliveries, and approve "
             "AI recovery plans when something goes wrong.")
    st.caption(f"{k['on_duty']} partners on duty · {k['deliveries']} deliveries · {k['open_issues']} open issues")
    st.page_link("views/manager.py", label="Open operations", icon=":material/arrow_forward:")
with right, st.container(border=True):
    st.markdown("#### :material/two_wheeler: Partner app")
    st.write("For delivery partners, on the phone. Your next stop, your route, and a one-tap voice note "
             "when there is a problem on the road.")
    st.caption("Works in English, Tamil and Tanglish")
    st.page_link("views/partner.py", label="Open partner app", icon=":material/arrow_forward:")

st.markdown("##### How it works")
steps = st.columns(3, gap="medium")
for col, (icon, title, text) in zip(steps, [
    ("mic", "Partner reports", "A voice note like “Avinashi road la accident, rendu mani neram” is enough."),
    ("psychology", "AI works it out", "Finds the place, the deliveries that will be late, and a plan – "
                                      "explained like a senior dispatcher would."),
    ("task_alt", "Manager approves", "One tap updates routes, ETAs, partner phones and customer messages."),
]):
    with col:
        st.markdown(f"**:material/{icon}: {title}**")
        st.caption(text)
