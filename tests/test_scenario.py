"""End-to-end checks for the Avinashi Road demo and the parser.

Run with:  python -m pytest -q
"""
import pytest

from modules.data_loader import load_all
from modules.impact import compute_impact
from modules.parser import parse_disruption
from modules.recommender import recommend
from modules.risk import score_risk

DEMO_TEXT = "Accident near Avinashi Road, road blocked for 2 hours"


@pytest.fixture(scope="module")
def data():
    return load_all()


@pytest.fixture(scope="module")
def demo(data):
    disruption = parse_disruption(DEMO_TEXT, data, use_llm=False)
    impact, summary = compute_impact(disruption, data)
    risk = score_risk(impact, disruption)
    actions, before_after, after = recommend(risk, disruption, data, polish=False)
    return {"disruption": disruption, "summary": summary, "risk": risk,
            "actions": actions, "before_after": before_after, "after": after}


# ---------------------------------------------------------------- demo scenario
def test_demo_is_parsed_correctly(demo):
    d = demo["disruption"]
    assert (d["type"], d["road_id"], d["severity"], d["duration_min"]) == ("accident", "R1", "critical", 120)


def test_three_vehicles_affected(demo):
    assert demo["summary"]["affected_vehicles"] == ["V1", "V2", "V3"]


def test_eight_to_ten_deliveries_affected(demo):
    assert 8 <= demo["summary"]["affected_deliveries"] <= 10


def test_critical_includes_medical_and_perishable(demo):
    critical = demo["risk"][demo["risk"]["risk_label"] == "Critical"]
    assert len(critical) >= 2
    assert "medical" in set(critical["priority"])
    assert "perishable" in set(critical["priority"])


def test_mix_of_risk_labels(demo):
    assert {"Critical", "High", "Medium", "Low"} <= set(demo["risk"]["risk_label"])


def test_recommendations_exist_and_explain_themselves(demo):
    assert demo["actions"]
    for action in demo["actions"]:
        assert action["why"]
        assert action["deliveries_protected"]
    assert any(a["action_type"] == "reassign" for a in demo["actions"])


def test_plan_reduces_missed_deadlines(demo):
    ba = demo["before_after"]
    assert ba["misses_before"] > 0
    assert ba["misses_after"] < ba["misses_before"]


def test_unknown_road_has_friendly_message(data):
    disruption = parse_disruption("Something happened somewhere", data, use_llm=False)
    impact, summary = compute_impact(disruption, data)
    assert impact.empty and "road" in summary["message"].lower()


def test_road_with_no_deliveries_has_no_impact(data):
    disruption = {"type": "closure", "road_id": "R1", "severity": "high", "duration_min": 60}
    empty = {**data, "deliveries": data["deliveries"].iloc[0:0]}
    impact, summary = compute_impact(disruption, empty)
    assert impact.empty and "no impact" in summary["message"].lower()


# ---------------------------------------------------------------- several disruptions at once
RAIN_TEXT = "Heavy rain flooding at Trichy Road, expect 45 mins delay"


@pytest.fixture(scope="module")
def two(data, demo):
    disruptions = [demo["disruption"], parse_disruption(RAIN_TEXT, data, use_llm=False)]
    impact, summary = compute_impact(disruptions, data)
    risk = score_risk(impact, disruptions)
    actions, before_after, after = recommend(risk, disruptions, data, polish=False)
    return {"summary": summary, "risk": risk, "actions": actions, "before_after": before_after}


def test_two_disruptions_widen_the_ripple(demo, two):
    assert set(demo["summary"]["affected_vehicles"]) < set(two["summary"]["affected_vehicles"])
    assert two["summary"]["affected_deliveries"] > demo["summary"]["affected_deliveries"]
    assert two["summary"]["affected_roads"] == ["Avinashi Road", "Trichy Road"]


def test_delivery_hit_twice_adds_both_delays(two):
    double = two["risk"][two["risk"]["disruption_ids"].apply(len) == 2]
    assert not double.empty
    for _, row in double.iterrows():
        assert row["delay_min"] == sum(p["delay_min"] for p in row["parts"])
        assert "hit by 2 disruptions" in row["reason"]


def test_reroutes_avoid_every_blocked_road(two):
    reroutes = [a for a in two["actions"] if a["action_type"] == "reroute"]
    assert reroutes
    for action in reroutes:
        assert not set(action["via_roads"]) & {"R1", "R2"}


def test_plan_helps_with_two_disruptions(two):
    ba = two["before_after"]
    assert ba["misses_after"] < ba["misses_before"]
    assert ba["critical_after"] < ba["critical_before"]


def test_single_dict_and_one_item_list_agree(data, demo):
    as_list_impact, _ = compute_impact([demo["disruption"]], data)
    as_dict_impact, _ = compute_impact(demo["disruption"], data)
    assert as_list_impact["delay_min"].tolist() == as_dict_impact["delay_min"].tolist()


# ---------------------------------------------------------------- parser
PARSER_CASES = [
    ("Accident near Avinashi Road, road blocked for 2 hours", "accident", "R1", None, 120),
    ("Heavy rain flooding at Trichy Road, expect 45 mins delay", "flood", "R2", None, 45),
    ("Van TN-37-AB-1234 puncture near Gandhipuram 100 feet road", "breakdown", "R7", "V1", None),
    ("Protest at Town Hall, traffic slow for 1.5 hr", "protest", "R10", None, 90),
    ("Traffic jam on Sathy Road around 30 mins", "traffic", "R4", None, 30),
    ("Avinashi road la accident aachu, full ah block, 2 mani neram aagum", "accident", "R1", None, 120),
    ("Mettupalayam road la mazhai romba, late aagum", "flood", "R3", None, None),
    ("Pollachi road closed for maintenance for 3 hrs", "closure", "R5", None, 180),
    ("Customer at RS Puram wants delivery earlier, deadline changed", "requirement_change", "R6", None, None),
    ("Murugan vandi breakdown aachu near Race Course", "breakdown", "R8", "V1", None),
]


@pytest.mark.parametrize("text, dtype, road, vehicle, duration", PARSER_CASES)
def test_parser(data, text, dtype, road, vehicle, duration):
    p = parse_disruption(text, data, use_llm=False)
    assert p["type"] == dtype
    assert p["road_id"] == road
    assert p["vehicle_id"] == vehicle
    if duration is not None:
        assert p["duration_min"] == duration
    assert p["method"] == "rules"


def test_tanglish_blockage_is_critical(data):
    p = parse_disruption("Avinashi road la accident aachu, full ah block, 2 mani neram aagum", data, use_llm=False)
    assert p["severity"] == "critical"
