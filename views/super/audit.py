"""Audit log: who did what, when."""
import json

import streamlit as st

from modules import guards, store, ui

guards.require_permission("view_audit_log")
ui.header("Audit log")

log = store.audit_df(500)
query = st.text_input("Search", placeholder="Action, person, branch", label_visibility="collapsed",
                      icon=":material/search:")
if query:
    hay = log.astype(str).apply(" ".join, axis=1).str.lower()
    log = log[hay.str.contains(query.lower(), regex=False)]
log = log.assign(details=log["details_json"].apply(lambda d: ", ".join(f"{k}: {v}" for k, v in json.loads(d or "{}").items())))
with ui.card("audit"):
    st.dataframe(log[["time", "actor", "action", "target", "branch_id", "details"]].rename(columns={
        "time": "Time", "actor": "Who", "action": "Action", "target": "Target", "branch_id": "Branch",
        "details": "Details"}), hide_index=True, width="stretch", height=540)
st.download_button("Download CSV", log.drop(columns=["details_json"]).to_csv(index=False), "deport-audit-log.csv",
                   "text/csv", icon=":material/download:")
