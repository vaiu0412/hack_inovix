"""My History: my reports, instructions I received and deliveries I completed."""
from html import escape

import streamlit as st

from modules import guards, partner_scope as scope, ui

guards.require_role("partner")
dp_id = guards.dp_id()
ui.header("My History", "Your reports, instructions and completed deliveries.")
ui.live_updates()

st.markdown("##### My reports")
reports = scope.get_partner_incidents(dp_id)
if not reports:
    st.caption("You haven't reported anything today.")
for r in reports:
    with st.container(border=True):
        st.markdown(f"**#{r['issue_id']}** · {escape(r['summary'] or '')} &nbsp; {ui.issue_badge(r['status'])}",
                    unsafe_allow_html=True)
        if r["transcript"]:
            st.markdown(f'<div class="rp-quote">“{escape(r["transcript"])}”</div>', unsafe_allow_html=True)
        if r["status"] == "accepted":
            st.caption(f"Handled at {r['decided_at']} · {r['headline']}")
        elif r["status"] == "rejected":
            st.caption(f"Reviewed at {r['decided_at']}: {r['decision_note']}")
        else:
            st.caption(f"Sent at {r['created_at']} · operations is reviewing")

st.markdown("##### Instructions received")
messages = scope.get_partner_notifications(dp_id)
if not messages:
    st.caption("No instructions yet.")
for m in messages:
    st.markdown(f"<small>{m['created_at']}</small> {escape(m['text'])}", unsafe_allow_html=True)

st.markdown("##### Delivered")
deliveries = scope.get_partner_deliveries(dp_id)
done = deliveries[deliveries["status"] == "delivered"]
if done.empty:
    st.caption("Nothing delivered yet.")
else:
    st.dataframe(done[["delivery_id", "customer", "address_area", "deadline"]].rename(
        columns={"delivery_id": "Order", "customer": "Customer", "address_area": "Area", "deadline": "Due"}),
        hide_index=True, width="stretch")
