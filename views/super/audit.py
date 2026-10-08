"""Audit Log: who did what, when (sign-ins, accounts, branches, decisions)."""
import json

import streamlit as st

from modules import guards, store, ui

guards.require_permission("view_audit_log")
ui.header("Audit Log", "Every sign-in, account change, branch change and decision.")

log = store.audit_df(500)
query = st.text_input("Filter", placeholder="Search action, person, target or branch", label_visibility="collapsed")
if query:
    hay = log.astype(str).apply(" ".join, axis=1).str.lower()
    log = log[hay.str.contains(query.lower(), regex=False)]
log = log.assign(details=log["details_json"].apply(lambda d: ", ".join(f"{k}: {v}" for k, v in json.loads(d or "{}").items())))
st.dataframe(log[["time", "actor", "action", "target", "branch_id", "details"]].rename(columns={
    "time": "Time", "actor": "Who", "action": "Action", "target": "Target", "branch_id": "Branch",
    "details": "Details"}), hide_index=True, width="stretch", height=560)
st.download_button("Download audit log (CSV)", log.drop(columns=["details_json"]).to_csv(index=False),
                   "ripple-audit-log.csv", "text/csv", icon=":material/download:")
