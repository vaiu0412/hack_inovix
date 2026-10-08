"""A partner's report (voice, text or a quick button) -> the actual problem.

preview() shows the partner what we understood before anything is sent.
submit() stores the issue and immediately asks the AI for a plan, so the
manager sees problem + recommendation together.
"""
from modules import store
from modules.parser import BASE_SEVERITY, DEFAULT_DURATION, parse_disruption
from modules.voice import transcribe

QUICK_TYPES = {
    "accident": "Accident",
    "traffic": "Heavy traffic",
    "breakdown": "Puncture / breakdown",
    "flood": "Rain / flooding",
    "closure": "Road blocked",
    "customer_unavailable": "Customer not available",
}
TYPE_LABELS = {**QUICK_TYPES, "protest": "Protest", "requirement_change": "Change in plans", "unknown": "Other"}


def type_label(dtype):
    return TYPE_LABELS.get(dtype, str(dtype).replace("_", " ").capitalize())


def route_roads(partner, data):
    """The partner's own roads in driving order: the easiest places to pick from."""
    vehicles = data["vehicles"].set_index("vehicle_id")
    roads = data["roads"].set_index("road_id")["name"]
    route = vehicles.loc[partner["vehicle_id"], "route_roads"] if partner["vehicle_id"] in vehicles.index else []
    return [(r, roads.get(r, r)) for r in route]


def understand(text, partner, data, quick_type=None):
    """Structured problem from free text, filled in with what we know about the reporter."""
    problem = parse_disruption(text or "", data)
    if quick_type and (problem["type"] == "unknown" or not (text or "").strip()):
        problem["type"] = quick_type
        problem["severity"] = BASE_SEVERITY.get(quick_type, "medium")
        problem["duration_min"] = DEFAULT_DURATION.get(quick_type, 60)

    problem["needs_location"] = False
    if problem["type"] == "breakdown" and not problem.get("vehicle_id"):
        problem["vehicle_id"] = partner["vehicle_id"]  # "my vehicle broke down"
    if problem["type"] == "customer_unavailable":
        delivery = _next_delivery(partner)
        problem["delivery_id"] = delivery["delivery_id"] if delivery is not None else None
        problem["customer"] = delivery["customer"] if delivery is not None else None
        problem["vehicle_id"] = problem.get("vehicle_id") or partner["vehicle_id"]
    if not problem.get("road_id") and problem["type"] not in ("breakdown", "customer_unavailable"):
        # no place recognised: ask the partner to tap one of their own roads
        problem["needs_location"] = True

    problem["reported_by"] = partner["partner_id"]
    problem["reporter_name"] = partner["name"]
    problem["summary"] = summarize(problem)
    return problem


def summarize(problem):
    """'Accident · Avinashi Road (near PSG Tech) · about 2 h · critical'"""
    parts = [type_label(problem["type"])]
    if problem.get("road_name"):
        place = problem.get("place")
        near = f" (near {place})" if place and place != problem["road_name"] else ""
        parts.append(f"{problem['road_name']}{near}")
    elif problem.get("vehicle_id") and problem["type"] == "breakdown":
        parts.append(f"vehicle {problem['vehicle_id']}")
    if problem.get("customer"):
        parts.append(f"{problem['customer']} ({problem['delivery_id']})")
    minutes = int(problem.get("duration_min") or 0)
    if minutes:
        parts.append(f"about {minutes // 60} h {minutes % 60} min".replace(" 0 min", "") if minutes >= 60
                     else f"about {minutes} min")
    parts.append(problem.get("severity", "medium"))
    return " · ".join(parts)


def set_location(problem, road_id, data):
    """Partner or manager picked the road by hand."""
    names = data["roads"].set_index("road_id")["name"]
    problem = {**problem, "road_id": road_id, "road_name": names.get(road_id), "place": names.get(road_id),
               "needs_location": False}
    problem["summary"] = summarize(problem)
    return problem


def preview(partner_id, text="", audio=None, quick_type=None):
    """What we understood (nothing is saved). Returns transcript, engine and problem."""
    partner = store.get_partner(partner_id)
    data = store.snapshot()
    transcript, engine = (text or "").strip(), "typed"
    if audio and not transcript:
        heard = transcribe(audio)
        if heard:
            transcript, engine = heard["text"], heard["engine"]
        else:
            engine = "not understood"
    problem = understand(transcript, partner, data, quick_type) if (transcript or quick_type) else None
    return {"transcript": transcript, "engine": engine, "problem": problem}


def submit(partner_id, problem, transcript="", engine="typed", audio=None, quick_type=None, source="partner"):
    """Save the issue, log it, and let the AI prepare a plan for the manager. Returns the issue id."""
    from modules import operations  # avoid a circular import

    issue_id = store.add_issue(partner_id, text=transcript, audio=audio, quick_type=quick_type, source=source)
    store.update_issue(issue_id, transcript=transcript, transcript_engine=engine, problem=problem,
                       summary=problem["summary"])
    who = problem.get("reporter_name") or partner_id
    store.log_event("issue", f"{who} reported: {problem['summary']}", issue_id)
    operations.analyse(issue_id)
    return issue_id


def _next_delivery(partner):
    deliveries = store.deliveries_df(partner["vehicle_id"], include_done=False)
    return deliveries.sort_values("eta_min").iloc[0] if len(deliveries) else None


if __name__ == "__main__":
    import os
    import tempfile
    from pathlib import Path

    os.environ["RIPPLE_DB"] = str(Path(tempfile.mkdtemp()) / "issues.db")
    store.init_db()
    for text, quick in [("Avinashi road la accident, full block, rendu mani neram aagum", None),
                        ("vandi puncture", None), ("", "traffic"), ("International road accident", None),
                        ("customer phone edukala, door locked", None)]:
        result = preview("P1", text=text, quick_type=quick)
        p = result["problem"]
        print(f"{text or '[quick: ' + quick + ']':58} -> {p['summary']:55} needs_location={p['needs_location']}")
    print("issues OK")
