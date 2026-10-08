"""Super Admin overview: every branch at a glance (summary level – no day-to-day operations)."""
from html import escape

import plotly.graph_objects as go
import streamlit as st

from modules import admin, guards, store, ui

guards.require_permission("view_all_branches")
ui.header("Overview", "All branches at a glance.")
ui.live_updates()

summary = store.branch_summaries()
admins = admin.branch_admins_df()
ui.kpi_row([
    ("Branches", len(summary), None),
    ("Active branches", int(summary["is_active"].sum()), None),
    ("Branch admins", int(admins["is_active"].sum()), f"{len(admins)} total"),
    ("Delivery partners", int(summary["partners"].sum()), None),
    ("Deliveries today", int(summary["deliveries"].sum()), f"{int(summary['delivered'].sum())} delivered"),
    ("Open critical", int(summary["critical"].sum()), "incidents"),
], tile_width=150)

st.markdown("##### Branches")
columns = st.columns(3, gap="small")
for i, b in enumerate(summary.to_dict("records")):
    with columns[i % 3], st.container(border=True):
        status = ui.badge("Active", "rp-low") if b["is_active"] else ui.badge("Inactive", "rp-neutral")
        st.markdown(f"**{escape(b['name'])}** &nbsp;{status}<br><small>{b['branch_id']} · admin: "
                    f"{escape(b['admin'])}</small>", unsafe_allow_html=True)
        st.markdown(ui.kv([("Partners", b["partners"]), ("Deliveries", f"{b['delivered']} / {b['deliveries']}"),
                           ("Delayed", b["delayed"]),
                           ("Critical", ui.risk_badge("Critical") + f" {b['critical']}" if b["critical"] else "0"),
                           ("Open issues", b["open_issues"])]), unsafe_allow_html=True)

st.markdown("##### Deliveries today by branch")
ink, grid = ("#E6EDF3", "rgba(230,237,243,.10)") if ui.is_dark() else ("#374151", "rgba(17,24,39,.08)")
chart = summary.sort_values("deliveries")
figure = go.Figure(go.Bar(
    y=chart["name"], x=chart["deliveries"], orientation="h", marker=dict(color=ui.BRAND, cornerradius=4),
    width=0.5, text=chart["deliveries"], textposition="outside", textfont=dict(color=ink),
    customdata=chart[["delivered", "delayed", "critical"]],
    hovertemplate="<b>%{y}</b><br>%{x} deliveries · %{customdata[0]} delivered<br>"
                  "%{customdata[1]} delayed · %{customdata[2]} critical<extra></extra>",
))
figure.update_layout(height=60 + 56 * len(chart), margin=dict(l=8, r=40, t=8, b=8), showlegend=False,
                     paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font=dict(color=ink),
                     xaxis=dict(showgrid=True, gridcolor=grid, zeroline=False, title=None),
                     yaxis=dict(showgrid=False, title=None))
st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
with st.expander("Table view"):
    st.dataframe(summary.rename(columns={"branch_id": "ID", "name": "Branch", "area": "Area", "is_active": "Active",
                                         "admin": "Admin", "partners": "Partners", "deliveries": "Deliveries",
                                         "delivered": "Delivered", "delayed": "Delayed", "critical": "Critical",
                                         "open_issues": "Open issues"}), hide_index=True, width="stretch")
