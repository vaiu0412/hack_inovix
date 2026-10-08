"""Dependency graph: Disruption -> Road -> Vehicle -> Delivery -> Customer/Deadline.

Built with NetworkX, drawn with Plotly in left-to-right layers.
Nodes are coloured by risk (Critical red ... Low green).
"""
import networkx as nx
import plotly.graph_objects as go

from modules.risk import LABEL_COLORS, LABEL_ORDER

LAYER_TITLES = ["Disruption", "Road", "Vehicle", "Delivery", "Customer · deadline"]
DISRUPTION_COLOR = "#dc2626"


def _worst(labels):
    labels = [l for l in labels if l in LABEL_ORDER]
    return min(labels, key=LABEL_ORDER.index) if labels else "Low"


def build_graph(disruption, risk_df, data):
    """Return a DiGraph with layer, label, color and hover attributes on each node."""
    g = nx.DiGraph()
    if risk_df is None or risk_df.empty:
        return g
    road_names = data["roads"].set_index("road_id")["name"]
    vehicles = data["vehicles"].set_index("vehicle_id")

    d_node = "disruption"
    g.add_node(d_node, layer=0, label=disruption.get("type", "disruption").replace("_", " ").title(),
               color=DISRUPTION_COLOR,
               hover=f"<b>{disruption.get('type', '').title()}</b><br>Severity: {disruption.get('severity')}"
                     f"<br>Duration: {disruption.get('duration_min')} min")

    blocked = disruption.get("road_id")
    if blocked:
        g.add_node(f"road:{blocked}", layer=1, label=road_names.get(blocked, blocked), color=DISRUPTION_COLOR,
                   hover=f"<b>{road_names.get(blocked, blocked)}</b><br>Blocked road")
        g.add_edge(d_node, f"road:{blocked}")

    df = risk_df.sort_values(["vehicle_id", "stop_order"])
    for vid, group in df.groupby("vehicle_id", sort=False):
        v = vehicles.loc[vid] if vid in vehicles.index else None
        worst = _worst(group["risk_label"])
        v_node = f"veh:{vid}"
        g.add_node(v_node, layer=2, label=vid, color=LABEL_COLORS[worst],
                   hover=f"<b>{vid}</b> {'' if v is None else v['reg_no']}<br>"
                         f"Driver: {'' if v is None else v['driver']}<br>{len(group)} affected stops · worst: {worst}")
        g.add_edge(f"road:{blocked}" if blocked else d_node, v_node)

        for _, row in group.iterrows():
            del_node = f"del:{row['delivery_id']}"
            color = LABEL_COLORS.get(row["risk_label"], "#94a3b8")
            g.add_node(del_node, layer=3, label=row["delivery_id"], color=color,
                       hover=f"<b>{row['delivery_id']}</b> · {row['priority']}<br>"
                             f"ETA {row['planned_eta']} → {row['new_eta']} (+{int(row['delay_min'])} min)<br>"
                             f"Risk {row['risk_score']} ({row['risk_label']})<br>{row['reason']}")
            g.add_edge(v_node, del_node)

            c_node = f"cust:{row['delivery_id']}"
            status = f"misses by {-row['slack_min']} min" if row["slack_min"] < 0 else f"{row['slack_min']} min slack"
            g.add_node(c_node, layer=4, label=f"{row['customer'][:26]} · {row['deadline']}", color=color,
                       hover=f"<b>{row['customer']}</b><br>{row['address_area']}<br>Deadline {row['deadline']} · {status}")
            g.add_edge(del_node, c_node)
    return g


def layered_positions(g):
    """x = layer, y = evenly spread in insertion order (keeps each vehicle's stops together).
    Vehicles, roads and the disruption sit at the average height of their children."""
    pos = {}
    leaves = [n for n in g.nodes if g.nodes[n]["layer"] == 4]
    for i, node in enumerate(leaves):
        pos[node] = (4, -i)
    for layer in [3, 2, 1, 0]:
        for node in [n for n in g.nodes if g.nodes[n]["layer"] == layer]:
            ys = [pos[c][1] for c in g.successors(node) if c in pos]
            pos[node] = (layer, sum(ys) / len(ys) if ys else 0)
    return pos


def render_graph(g, height=None):
    """Plotly figure of the layered graph."""
    fig = go.Figure()
    if g.number_of_nodes() == 0:
        fig.add_annotation(text="No impact to show", showarrow=False, font=dict(size=16))
        fig.update_layout(height=200, xaxis_visible=False, yaxis_visible=False)
        return fig

    pos = layered_positions(g)

    edge_x, edge_y = [], []
    for a, b in g.edges():
        edge_x += [pos[a][0], pos[b][0], None]
        edge_y += [pos[a][1], pos[b][1], None]
    fig.add_trace(go.Scatter(x=edge_x, y=edge_y, mode="lines", hoverinfo="skip",
                             line=dict(width=1.2, color="rgba(148,163,184,0.55)"), showlegend=False))

    nodes = list(g.nodes())
    last = [n for n in nodes if g.nodes[n]["layer"] == 4]
    others = [n for n in nodes if g.nodes[n]["layer"] != 4]
    for subset, text_pos in [(others, "top center"), (last, "middle right")]:
        fig.add_trace(go.Scatter(
            x=[pos[n][0] for n in subset], y=[pos[n][1] for n in subset],
            mode="markers+text", text=[g.nodes[n]["label"] for n in subset], textposition=text_pos,
            textfont=dict(size=11),
            hovertext=[g.nodes[n]["hover"] for n in subset], hoverinfo="text",
            marker=dict(size=[26 if g.nodes[n]["layer"] < 3 else 16 for n in subset],
                        color=[g.nodes[n]["color"] for n in subset],
                        line=dict(width=1.5, color="rgba(15,23,42,0.6)")),
            showlegend=False,
        ))

    # legend entries for risk colours
    for label in LABEL_ORDER:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers", name=label,
                                 marker=dict(size=10, color=LABEL_COLORS[label])))

    n_rows = max(sum(1 for n in nodes if g.nodes[n]["layer"] == layer) for layer in range(5))
    fig.update_layout(
        height=height or max(380, 42 * n_rows + 80),
        margin=dict(l=10, r=10, t=40, b=40),
        xaxis=dict(visible=False, range=[-0.4, 5.6]),
        yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=-0.02, x=0, yanchor="top"),
        hoverlabel=dict(align="left"),
    )
    for i, title in enumerate(LAYER_TITLES):
        fig.add_annotation(x=i, y=1.0, yref="paper", text=f"<b>{title}</b>", showarrow=False,
                           font=dict(size=12, color="#94a3b8"), yanchor="bottom")
    return fig


if __name__ == "__main__":
    from modules.data_loader import load_all
    from modules.impact import compute_impact
    from modules.parser import parse_disruption
    from modules.risk import score_risk

    data = load_all()
    demo = parse_disruption("Accident near Avinashi Road, road blocked for 2 hours", data, use_llm=False)
    risk = score_risk(compute_impact(demo, data)[0], demo)
    graph = build_graph(demo, risk, data)
    print("nodes:", graph.number_of_nodes(), "edges:", graph.number_of_edges())
    fig = render_graph(graph)
    print("traces:", len(fig.data))
    print("graph_viz OK")
