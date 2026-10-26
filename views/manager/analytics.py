"""Analytics: where and when delays happen, the service level, how partners perform and how accurate the delay
model is. History charts use the synthetic 60-day history (labelled); partner and disruption data are live."""
import folium
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from folium.plugins import HeatMap
from streamlit_folium import st_folium

from modules import analytics, guards, live_map, ui
from modules import manager_ui as mui

guards.require_role("branch_admin")
ui.header("Analytics", "Delays, service level, partners, model")
ctx = mui.context()
summary = analytics.history_summary()
performance = analytics.partner_performance(ctx["branch_id"])
answers = analytics.response_times(ctx["branch_id"])
spots = analytics.disruption_points(ctx["branch_id"], ctx["roads"])
delivered, on_time = analytics.today_sla(ctx["branch_id"])

# one sequential hue (blue): low values sink into the surface, high values stand out
SCALE = ([[0, "#15233D"], [0.5, "#2563EB"], [1, "#BFDBFE"]] if ui.is_dark()
         else [[0, "#EFF6FF"], [0.5, "#60A5FA"], [1, "#1E3A8A"]])
SYNTHETIC = ui.badge("Synthetic history", "rp-neutral")
LIVE = ui.badge("Live", "rp-brand")


def heading(title, icon_name, tag):
    st.markdown(f'<p class="dp-h2">{ui.icon(icon_name)}{title} {tag}</p>', unsafe_allow_html=True)


def chart(figure):
    st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})


ui.kpi_cards([
    ("task_alt", delivered, "Delivered today", f"{on_time} on time" if delivered else "none yet", "normal"),
    ("schedule", f"{on_time / delivered:.0%}" if delivered else "—", "On time today", None,
     "normal" if not delivered or on_time / delivered >= 0.9 else "delayed"),
    ("timer", f"{answers['minutes'].mean():.1f} min" if len(answers) else "—", "Offer answer time",
     f"{len(answers)} answered" if len(answers) else "no offers yet", None),
    ("warning", len(spots), "Disruptions", "this branch", "critical" if spots else "normal"),
    ("model_training", f"{summary['accuracy']['mae_min']} min" if summary else "—", "Model error",
     "mean, test days" if summary else "no summary", "navy"),
])

# ---------------------------------------------------------------- delays by road × hour (history)
heading("Delays by road and hour", "grid_on", SYNTHETIC)
with ui.card("delay_grid"):
    grid = analytics.delay_matrix(summary)
    if grid.empty:
        ui.empty_state("grid_off", "No history summary. Run ml/summarise_history.py.")
    else:
        hours = [f"{h:02d}:00" for h in grid.columns]
        figure = go.Figure(go.Heatmap(
            z=grid.to_numpy(), x=hours, y=list(grid.index), colorscale=SCALE, zmin=0, xgap=2, ygap=2,
            colorbar=dict(title=dict(text="min late", side="right"), thickness=10, outlinewidth=0),
            hovertemplate="<b>%{y}</b> · %{x}<br>%{z:.1f} min late on average<extra></extra>"))
        ui.style_figure(figure, height=60 + 34 * len(grid))
        figure.update_xaxes(showgrid=False, side="top")
        figure.update_yaxes(autorange="reversed")
        chart(figure)
        st.caption(f"Mean minutes late vs plan · {summary['rows']:,} synthetic deliveries, "
                   f"{summary['from']} – {summary['to']} · worst roads first · cells with under "
                   f"{analytics.MIN_CELL} deliveries left out.")
        with st.expander("Table view", icon=":material/table:"):
            st.dataframe(grid.rename(columns=lambda h: f"{h:02d}:00").round(1), width="stretch")

left, right = st.columns(2, gap="medium")
# ---------------------------------------------------------------- service level per day (history)
with left:
    heading("On time per day", "trending_up", SYNTHETIC)
    with ui.card("sla_trend"):
        trend = analytics.sla_trend(summary)
        if trend.empty:
            ui.empty_state("show_chart", "No history summary.")
        else:
            figure = go.Figure(go.Scatter(
                x=trend["date"], y=trend["on_time"] * 100, mode="lines", line=dict(color=ui.BRAND, width=2),
                customdata=trend["n"], hovertemplate="%{x|%a %d %b}<br><b>%{y:.1f}%</b> on time "
                                                     "(%{customdata} deliveries)<extra></extra>"))
            ui.style_figure(figure, height=280)
            figure.update_layout(hovermode="x unified", yaxis=dict(ticksuffix="%", title=None))
            figure.update_xaxes(showgrid=False)
            figure.update_yaxes(showgrid=True, gridcolor="rgba(148,163,184,.14)")
            chart(figure)
            st.caption("Share delivered by the deadline, per day.")
            with st.expander("Table view", icon=":material/table:"):
                st.dataframe(trend.assign(date=trend["date"].dt.date, on_time=(trend["on_time"] * 100).round(1))
                             .rename(columns={"date": "Date", "on_time": "On time %", "n": "Deliveries"}),
                             hide_index=True, width="stretch")

# ---------------------------------------------------------------- disruption heatmap (live)
with right:
    heading("Where disruptions happen", "local_fire_department", LIVE)
    with ui.card("disruption_heat"):
        if not spots:
            ui.empty_state("map", "No disruptions yet. They show here once a plan is applied.")
        else:
            m = folium.Map(location=live_map.COIMBATORE_CENTER, zoom_start=12, tiles=None, scrollWheelZoom=False)
            live_map.add_tiles(m, switcher=False)
            HeatMap([list(p) for p in spots], radius=26, blur=20, min_opacity=0.35,
                    gradient={0.2: "#1E3A8A", 0.5: "#2563EB", 0.8: "#60A5FA", 1.0: "#DBEAFE"}).add_to(m)
            m.fit_bounds([[p[0], p[1]] for p in spots], padding=(30, 30), max_zoom=14)
            st_folium(m, height=280, use_container_width=True, key="analytics_heat", returned_objects=[])
            st.caption(f"{len(spots)} disruption{'' if len(spots) == 1 else 's'}, weighted by severity.")

# ---------------------------------------------------------------- partner performance (live)
heading("Partner performance", "groups", LIVE)
with ui.card("partner_perf"):
    if performance.empty:
        ui.empty_state("group_off", "No partners in this branch.")
    else:
        table = performance.assign(on_time=performance["on_time"] * 100).sort_values(
            ["delivered", "on_time"], ascending=False)
        st.dataframe(
            table.drop(columns=["partner_id"]), hide_index=True, width="stretch",
            column_config={
                "name": st.column_config.TextColumn("Partner"),
                "delivered": st.column_config.NumberColumn("Delivered"),
                "on_time": st.column_config.ProgressColumn("On time", min_value=0, max_value=100, format="%.0f%%"),
                "open": st.column_config.NumberColumn("Open"),
                "answered": st.column_config.NumberColumn("Offers answered"),
                "answer_min": st.column_config.NumberColumn("Answer time", format="%.1f min"),
                "declined": st.column_config.NumberColumn("Declined"),
            })
        st.caption("Today, this branch. On time = delivered within the promised time (by the stop's ETA on the "
                   "demo clock). Answer time = offer sent → accepted or declined.")

# ---------------------------------------------------------------- prediction accuracy (history)
heading("Prediction accuracy", "model_training", SYNTHETIC)
by_road, reliability = analytics.accuracy(summary)
left, right = st.columns(2, gap="medium")
with left, ui.card("mae_by_road"):
    if by_road.empty:
        ui.empty_state("bar_chart", "No history summary.")
    else:
        shown = by_road.sort_values("mae_min")
        figure = go.Figure(go.Bar(
            y=shown["road"], x=shown["mae_min"], orientation="h", width=0.6, marker=dict(color=ui.BRAND,
                                                                                        cornerradius=4),
            customdata=shown["n"], hovertemplate="<b>%{y}</b><br>off by %{x:.1f} min on average "
                                                 "(%{customdata} deliveries)<extra></extra>"))
        ui.style_figure(figure, height=60 + 30 * len(shown))
        figure.update_layout(xaxis=dict(title=None, ticksuffix=" min"), yaxis=dict(title=None))
        chart(figure)
        acc = summary["accuracy"]
        st.caption(f"Delay error per road (MAE) · test days {acc['test_from']} – {acc['test_to']}, "
                   f"{acc['test_rows']:,} deliveries.")
        with st.expander("Table view", icon=":material/table:"):
            st.dataframe(by_road.rename(columns={"road": "Road", "mae_min": "MAE (min)", "n": "Deliveries"}),
                         hide_index=True, width="stretch")
with right, ui.card("reliability"):
    if reliability.empty:
        ui.empty_state("scatter_plot", "No history summary.")
    else:
        figure = go.Figure()
        figure.add_shape(type="line", x0=0, y0=0, x1=100, y1=100, line=dict(color="rgba(148,163,184,.5)", width=1,
                                                                           dash="dot"))
        figure.add_annotation(x=88, y=96, text="perfect", showarrow=False, font=dict(size=11, color="#94A3B8"))
        figure.add_trace(go.Scatter(
            x=reliability["predicted"] * 100, y=reliability["actual"] * 100, mode="lines+markers",
            line=dict(color=ui.BRAND, width=2), marker=dict(size=9, color=ui.BRAND,
                                                            line=dict(width=2, color="#0B1220")),
            customdata=reliability["n"], hovertemplate="said %{x:.0f}% late → %{y:.0f}% were late"
                                                       "<br>%{customdata} deliveries<extra></extra>"))
        ui.style_figure(figure, height=60 + 30 * len(by_road))
        figure.update_layout(xaxis=dict(title="Predicted chance late", range=[0, 100], ticksuffix="%"),
                             yaxis=dict(title="Really late", range=[0, 100], ticksuffix="%"))
        figure.update_yaxes(showgrid=True, gridcolor="rgba(148,163,184,.14)")
        chart(figure)
        st.caption(f"Close to the dotted line = the chance is honest · Brier score "
                   f"{summary['accuracy']['brier']}.")
        with st.expander("Table view", icon=":material/table:"):
            st.dataframe(pd.DataFrame({
                "Predicted": [f"{a:.0%}–{b:.0%}" for a, b in zip(reliability["from"], reliability["to"])],
                "Mean predicted": (reliability["predicted"] * 100).round(1),
                "Really late %": (reliability["actual"] * 100).round(1), "Deliveries": reliability["n"]}),
                hide_index=True, width="stretch")
