"""Overview: every branch at a glance (summary level – no day-to-day operations)."""
from html import escape

import plotly.graph_objects as go
import streamlit as st

from modules import admin, guards, store, ui

guards.require_permission("view_all_branches")
ui.header("Overview", "All branches")

summary = store.branch_summaries()
admins = admin.branch_admins_df()
critical = int(summary["critical"].sum())
ui.kpi_cards([
    ("store", len(summary), "Branches", f"{int(summary['is_active'].sum())} active", "navy"),
    ("admin_panel_settings", int(admins["is_active"].sum()), "Admins", f"of {len(admins)}", None),
    ("groups", int(summary["partners"].sum()), "Partners", None, None),
    ("package_2", int(summary["deliveries"].sum()), "Deliveries", f"{int(summary['delivered'].sum())} done", None),
    ("notifications_active", int(summary["open_issues"].sum()), "Open alerts", None,
     "critical" if summary["open_issues"].sum() else "normal"),
    ("emergency", critical, "Critical", None, "critical" if critical else "normal"),
])

ui.section("Branches", "store")
columns = st.columns(3, gap="small")
for i, b in enumerate(summary.to_dict("records")):
    with columns[i % 3], ui.card(f"branch_{b['branch_id']}"):
        status = ui.pill_html("normal", "Active") if b["is_active"] else ui.pill_html("off", "Inactive")
        st.markdown(f"<p class='dp-h3'>{escape(b['name'])}</p><p class='dp-small'>{b['branch_id']} · "
                    f"{escape(b['admin'])}</p><div style='margin:8px 0'>{status}</div>", unsafe_allow_html=True)
        st.markdown(ui.kv([("Partners", b["partners"]), ("Done", f"{b['delivered']} / {b['deliveries']}"),
                           ("Delayed", b["delayed"]),
                           ("Critical", ui.pill_html("critical", str(b["critical"])) if b["critical"] else "0"),
                           ("Alerts", b["open_issues"])]), unsafe_allow_html=True)

ui.section("Deliveries by branch", "bar_chart")
chart = summary.sort_values("deliveries")
figure = go.Figure(go.Bar(
    y=chart["name"], x=chart["deliveries"], orientation="h", marker=dict(color=ui.BRAND, cornerradius=4),
    width=0.5, text=chart["deliveries"], textposition="outside",
    customdata=chart[["delivered", "delayed", "critical"]],
    hovertemplate="<b>%{y}</b><br>%{x} deliveries · %{customdata[0]} done<br>"
                  "%{customdata[1]} delayed · %{customdata[2]} critical<extra></extra>",
))
ui.style_figure(figure, height=60 + 56 * len(chart))
figure.update_layout(xaxis=dict(title=None), yaxis=dict(title=None))
with ui.card("chart"):
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
with st.expander("Table view", icon=":material/table:"):
    st.dataframe(summary.rename(columns={"branch_id": "ID", "name": "Branch", "area": "Area", "is_active": "Active",
                                         "admin": "Admin", "partners": "Partners", "deliveries": "Deliveries",
                                         "delivered": "Done", "delayed": "Delayed", "critical": "Critical",
                                         "open_issues": "Alerts"}), hide_index=True, width="stretch")
