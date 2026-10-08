"""Score each affected delivery 0-100 and label it Critical / High / Medium / Low.

risk = 45 x deadline pressure   (biggest: little or negative slack)
     + 30 x priority weight     (medical > perishable > express > standard)
     + 10 x cascade position    (closer to the disruption = more exposed)
     + 15 x severity
"""
import pandas as pd

WEIGHTS = {"slack": 45, "priority": 30, "cascade": 10, "severity": 15}
PRIORITY_WEIGHT = {"medical": 1.0, "perishable": 0.8, "express": 0.5, "standard": 0.1}
SEVERITY_WEIGHT = {"low": 0.25, "medium": 0.5, "high": 0.75, "critical": 1.0}
SLACK_HORIZON_MIN = 150  # slack beyond this counts as "no pressure"

LABEL_ORDER = ["Critical", "High", "Medium", "Low"]
LABEL_COLORS = {"Critical": "#ef4444", "High": "#f97316", "Medium": "#eab308", "Low": "#22c55e",
                "On track": "#38bdf8"}


def risk_label(score):
    if score >= 75:
        return "Critical"
    if score >= 50:
        return "High"
    if score >= 25:
        return "Medium"
    return "Low"


def slack_pressure(slack_min):
    if slack_min < 0:
        return 1.0
    return max(0.0, 1 - slack_min / SLACK_HORIZON_MIN)


def cascade_exposure(cascade_index):
    return max(0.0, 1 - cascade_index / 3)


def _ordinal(n):
    return {1: "1st", 2: "2nd", 3: "3rd"}.get(n, f"{n}th")


def make_reason(row):
    if row["slack_min"] < 0:
        parts = [f"misses {row['deadline']} deadline by {-row['slack_min']} min"]
    else:
        parts = [f"{row['slack_min']} min slack before {row['deadline']}"]
    parts.append(row["priority"])
    if row["on_blocked_road"]:
        parts.append("on the blocked road")
    else:
        parts.append(f"{_ordinal(row['cascade_index'] + 1)} stop downstream")
    return " · ".join(parts)


def score_risk(impact, disruption):
    """Add risk_score, risk_label and reason columns; return sorted by risk."""
    if impact.empty:
        return impact.assign(risk_score=pd.Series(dtype=float), risk_label=pd.Series(dtype=str),
                             reason=pd.Series(dtype=str))
    df = impact.copy()
    severity = SEVERITY_WEIGHT.get(disruption.get("severity", "medium"), 0.5)
    # parcels moved to another vehicle are no longer exposed to the disruption
    exposed = ~df["off_route"] if "off_route" in df.columns else True
    df["risk_score"] = (
        WEIGHTS["slack"] * df["slack_min"].apply(slack_pressure)
        + WEIGHTS["priority"] * df["priority"].map(PRIORITY_WEIGHT).fillna(0.1)
        + (WEIGHTS["cascade"] * df["cascade_index"].apply(cascade_exposure)
           + WEIGHTS["severity"] * severity) * exposed
    ).round(1)
    df["risk_label"] = df["risk_score"].apply(risk_label)
    df["reason"] = df.apply(make_reason, axis=1)
    return df.sort_values("risk_score", ascending=False).reset_index(drop=True)


if __name__ == "__main__":
    from modules.data_loader import load_all
    from modules.impact import compute_impact
    from modules.parser import parse_disruption

    data = load_all()
    demo = parse_disruption("Accident near Avinashi Road, road blocked for 2 hours", data, use_llm=False)
    risk = score_risk(compute_impact(demo, data)[0], demo)
    print(risk[["delivery_id", "priority", "slack_min", "risk_score", "risk_label", "reason"]].to_string(index=False))
    print(risk["risk_label"].value_counts().to_dict())
    critical = risk[risk["risk_label"] == "Critical"]
    assert len(critical) >= 2 and "medical" in set(critical["priority"])
    print("risk OK")
