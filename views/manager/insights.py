"""Insights: how the branch decides on recommendations – what is taken, skipped or changed – and the model that
learns from it to rank the next plans (chance taken × impact)."""
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from modules import guards, learning, ui
from modules import manager_ui as mui

guards.require_role("branch_admin")
ui.header("Insights", "What admins take, skip and change")
ctx = mui.context()
data = learning.insights(ctx["branch_id"])
model = data["model"]

if not data["decisions"]:
    with ui.card("no_decisions"):
        ui.empty_state("insights", "No decisions yet. Accept, skip or reject a plan and it shows up here.")
        if st.button("Load sample history (demo)", icon=":material/dataset:", key="sample_history"):
            count = learning.sample_history(ctx["branch_id"])
            st.toast(f"{count} sample decisions added.", icon=":material/check:")
            st.rerun()

taken = sum(t["taken"] for t in data["by_type"] if t["action_type"] != "optimised_plan")
decided = sum(t["decided"] for t in data["by_type"] if t["action_type"] != "optimised_plan")
ui.kpi_cards([
    ("gavel", data["decisions"], "Decisions",
     f"{data['sample_rows']} sample" if data["sample_rows"] else "logged", "navy"),
    ("thumb_up", f"{taken / decided:.0%}" if decided else "—", "Taken", f"{taken} of {decided} recommendations",
     "normal"),
    ("check_circle", data["plans_accepted"], "Plans accepted", None, "normal"),
    ("cancel", data["plans_rejected"], "Plans rejected", None, "critical" if data["plans_rejected"] else "normal"),
    ("model_training", model["rows"] if model else data["learnable"], "Model",
     "trained on decisions" if model else f"learning · needs {learning.MIN_ROWS}", None),
])

chart_col, side_col = st.columns([1.4, 1], gap="medium")
with chart_col:
    ui.section("Taken by action type", "bar_chart")
    with ui.card("by_type"):
        rows = [t for t in data["by_type"] if t["decided"]]
        if rows:
            table = pd.DataFrame(rows).sort_values("rate")
            figure = go.Figure(go.Bar(
                y=table["label"], x=table["rate"] * 100, orientation="h", width=0.55,
                marker=dict(color=ui.BRAND, cornerradius=4), text=[f"{t}/{d}" for t, d in
                                                                   zip(table["taken"], table["decided"])],
                textposition="outside", customdata=table[["skipped", "rejected", "modified"]],
                hovertemplate="<b>%{y}</b><br>%{x:.0f}% taken (%{text})<br>skipped %{customdata[0]} · "
                              "rejected %{customdata[1]} · modified %{customdata[2]}<extra></extra>"))
            ui.style_figure(figure, height=70 + 52 * len(table))
            figure.update_layout(xaxis=dict(title=None, range=[0, 110], ticksuffix="%"), yaxis=dict(title=None))
            st.plotly_chart(figure, width="stretch", config={"displayModeBar": False})
            st.caption("Taken = accepted (or chosen) out of accepted + skipped + rejected. "
                       "Modified and replaced are counted, not learned from.")
            with st.expander("Table view", icon=":material/table:"):
                st.dataframe(pd.DataFrame(rows)[["label", "taken", "decided", "skipped", "rejected", "modified",
                                                 "replaced"]].rename(columns=str.capitalize),
                             hide_index=True, width="stretch")
        else:
            ui.empty_state("bar_chart", "Nothing decided yet.")

with side_col:
    ui.section("What the model learned", "model_training")
    with ui.card("model"):
        if model:
            metrics = model.get("metrics", {})
            quality = (f"holdout accuracy {metrics['holdout_accuracy']:.0%} · AUC {metrics['holdout_auc']:.2f}"
                       if metrics.get("holdout_auc") is not None
                       else f"training accuracy {metrics.get('train_accuracy', 0):.0%}")
            up, down = data["drivers"]
            st.markdown(
                f"<p class='dp-small'>Logistic regression · {model['rows']} decisions ({model['accepted']} taken) · "
                f"{escape(quality)} · trained {escape(model['trained_at'])}</p>"
                + "".join(f"<div class='dp-row'><div class='main'>{ui.icon('trending_up')} {escape(name)}</div>"
                          f"<div class='end'>{ui.pill_html('normal', f'+{w:.2f}')}</div></div>" for name, w in up)
                + "".join(f"<div class='dp-row'><div class='main'>{ui.icon('trending_down')} {escape(name)}</div>"
                          f"<div class='end'>{ui.pill_html('critical', f'{w:.2f}')}</div></div>" for name, w in down),
                unsafe_allow_html=True)
        else:
            st.markdown(f"<p class='dp-small'>No model yet: {data['learnable']} of {learning.MIN_ROWS} decisions "
                        "needed (with both taken and turned-down ones). Until then plans are ranked by each action "
                        "type's acceptance rate.</p>", unsafe_allow_html=True)
        if st.button("Retrain now", icon=":material/refresh:", key="retrain", width="stretch"):
            result = learning.train(ctx["actor"])
            if result["trained"]:
                st.toast(f"Model retrained on {result['rows']} decisions.", icon=":material/check:")
                st.rerun()
            else:
                st.warning(result["reason"], icon=":material/info:")
        st.caption("Plans list recommendations by chance taken × impact (minutes saved + 10 per delivery "
                   "protected). Retrains by itself once a day.")

    ui.section("Most changed", "edit_note")
    with ui.card("most_changed"):
        if data["most_changed"]:
            rows = []
            for r in data["most_changed"]:
                label = learning.ACTION_LABEL.get(r["action_type"], r["action_type"])
                rows.append(f"<div class='dp-row'><div class='main'>{escape(label)}</div><div class='end'>"
                            f"{ui.pill_html('delayed', r['decision'])} {r['times']}×</div></div>")
            st.markdown("".join(rows), unsafe_allow_html=True)
        else:
            ui.empty_state("edit_off", "Nothing skipped or modified yet.")

ui.section("Recent decisions", "history")
with ui.card("recent"):
    if data["recent"]:
        state = {"accepted": "normal", "chosen": "normal", "skipped": "delayed", "modified": "delayed",
                 "replaced": "available", "not_chosen": "off", "rejected": "critical"}
        rows = []
        for r in data["recent"]:
            who = escape(r["decided_by"] or "") + (f" · {escape(r['reason'])}" if r["reason"] else "")
            pill = ui.pill_html(state.get(r["decision"], "off"), r["decision"].replace("_", " "))
            rows.append(f"<div class='dp-row'><div class='main'><b>{escape(str(r['title'] or ''))}</b>"
                        f"<small>{who}</small></div><div class='end'>{pill}<br>"
                        f"<small>{escape(r['time'][5:16])}</small></div></div>")
        st.markdown("".join(rows), unsafe_allow_html=True)
    else:
        ui.empty_state("history", "No decisions yet.")
