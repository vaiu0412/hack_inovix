"""Notifications: every instruction from my branch, newest first."""
from html import escape

import streamlit as st

from modules import guards, partner_scope as scope, ui

guards.require_role("partner")
dp_id = guards.dp_id()
branch = guards.branch_id()
ui.header("Notifications", "Instructions from your branch.")
ui.live_updates()

messages = scope.get_partner_notifications(dp_id, branch)
unread = [m for m in messages if not m["read"]]
if unread and st.button(f"Mark {len(unread)} as read", icon=":material/done_all:", type="primary", width="stretch"):
    scope.mark_notifications_read(dp_id, branch)
    st.rerun()
if not messages:
    st.info("No notifications yet.", icon=":material/notifications_none:")
for m in messages:
    with st.container(border=True):
        tag = ui.badge("New", "rp-brand") if not m["read"] else ""
        st.markdown(f"<small>{m['created_at']}</small> &nbsp;{tag}<br>{escape(m['text'])}", unsafe_allow_html=True)
