"""WHAT SHOULD WE DO NEXT? Turn risk-scored impact into a recovery plan.

Rules (most urgent first):
- Critical medical/perishable -> reassign to the nearest idle backup vehicle
  (if the backup can still make the deadline), otherwise reroute.
- Critical (other) / High     -> reroute the vehicle via the best alternate road.
- Medium                      -> resequence: prioritise the stop.
- Low                         -> reschedule and notify the customer.
Every action carries a plain-English "why" and drafted messages.
Works for one disruption or several at once (detours never use another blocked road).
"""
import json
import re

from modules.data_loader import NOW_MIN, haversine_km, min_to_hhmm
from modules.impact import CASCADE_STEP_MIN, as_list
from modules.parser import call_llm, json_from_text, llm_available
from modules.risk import score_risk

URBAN_SPEED_KMPH = 25    # backup van average speed in the city
ROAD_FACTOR = 1.3        # real roads are ~30% longer than straight lines
HANDOVER_MIN = 5         # parcel transfer between vehicles
DROP_MIN = 5             # time at each customer
REROUTE_CONGESTION_MIN = 10  # everyone else is diverting too
RESCHEDULE_BUFFER_MIN = 30

TYPE_WORDS = {
    "accident": "an accident", "closure": "a road closure", "flood": "flooding",
    "breakdown": "a vehicle breakdown", "traffic": "heavy traffic", "protest": "a protest",
    "requirement_change": "a change in plans", "customer_unavailable": "the customer not being available",
    "unknown": "a disruption",
}


# ---------------------------------------------------------------- helpers
def travel_min(km):
    return km * ROAD_FACTOR / URBAN_SPEED_KMPH * 60


def find_alternate_road(blocked_road_id, data, avoid=()):
    """Pick the unblocked road whose ends connect best to the blocked road.

    avoid: other road_ids that are blocked too and must not be used.
    Returns (alt_row, extra_km) or (None, 0).
    extra_km = connector distances to/from the alternate + any extra length.
    """
    roads = data["roads"].set_index("road_id")
    if blocked_road_id not in roads.index:
        return None, 0.0
    blocked = roads.loc[blocked_road_id]
    start, end = blocked["points"][0], blocked["points"][-1]
    best = None
    for road_id, road in roads.iterrows():
        if road_id == blocked_road_id or road_id in avoid:
            continue
        a, b = road["points"][0], road["points"][-1]
        # the alternate can be driven in either direction
        connectors = min(haversine_km(*start, *a) + haversine_km(*b, *end),
                         haversine_km(*start, *b) + haversine_km(*a, *end))
        extra = connectors + max(0.0, road["length_km"] - blocked["length_km"])
        if best is None or extra < best[1]:
            best = (road.copy(), extra)
    if best is None:
        return None, 0.0
    alt, extra = best
    alt["road_id"] = alt.name
    return alt, round(max(extra, 0.5), 1)


def nearest_backup(data, lat, lng):
    backups = data["vehicles"].set_index("vehicle_id")
    backups = backups[backups["status"] == "backup"]
    if backups.empty:
        return None
    dist = backups.apply(lambda v: haversine_km(v["current_lat"], v["current_lng"], lat, lng), axis=1)
    return backups.loc[dist.idxmin()]


def _numbers(text):
    return set(re.findall(r"\d+(?:[.:]\d+)?", text))


def polish_whys(whys):
    """Optionally let the LLM smooth all "why" texts in ONE request.

    Any line where the LLM dropped or changed a number/time keeps the template text.
    """
    if not whys or not llm_available():
        return whys
    numbered = "\n".join(f"{i + 1}. {w}" for i, w in enumerate(whys))
    prompt = ("Rewrite each numbered line as one short, plain-English sentence for a delivery dispatcher. "
              "Keep every number, name, vehicle id and time exactly. "
              'Return ONLY JSON: {"whys": [one string per line, same order]}\n\n' + numbered)
    try:
        out = json_from_text(call_llm(prompt, want_json=True)).get("whys", [])
    except Exception:
        return whys
    if len(out) != len(whys):
        return whys
    return [new.strip() if isinstance(new, str) and new.strip() and _numbers(old) <= _numbers(new) else old
            for old, new in zip(whys, out)]


def _customer_sms(row, eta, extra=""):
    return (f"Hi {row['customer']}, your delivery {row['delivery_id']} is delayed due to "
            f"{row['_cause']}. {extra}New ETA: {eta}. Sorry for the trouble. – Ripple Logistics")


# ---------------------------------------------------------------- main
def recommend(impact, disruptions, data, polish=True):
    """Return (actions, before_after, after_df).

    actions: list of dicts with action_type, target, description,
             expected_delay_saved_min, extra_km, deliveries_protected, why, messages
    before_after: predicted misses / delay / critical counts before vs after
    after_df: impact rows with new vehicle, ETA and risk after applying the plan
    """
    if impact.empty:
        return [], {"misses_before": 0, "misses_after": 0, "delay_before": 0, "delay_after": 0,
                    "critical_before": 0, "critical_after": 0}, impact
    disruptions = as_list(disruptions)
    if "risk_label" not in impact.columns:
        impact = score_risk(impact, disruptions)

    vehicles = data["vehicles"].set_index("vehicle_id")
    road_names = data["roads"].set_index("road_id")["name"]

    def name_of(road_id):
        return road_names.get(road_id, "the affected road")

    # roads that are really blocked (a breakdown only stops its own vehicle)
    road_type = {d["road_id"]: d.get("type") for d in disruptions
                 if d.get("road_id") and d.get("type") not in ("breakdown", "requirement_change",
                                                               "customer_unavailable")}
    blocked_roads = set(road_type)

    after = impact.copy()
    after["_cause"] = after.apply(
        lambda r: f"{TYPE_WORDS.get(r['cause_type'], 'a disruption')} on {name_of(r['cause_road_id'])}", axis=1)
    after["_broken"] = after["parts"].apply(lambda ps: any(p["type"] == "breakdown" for p in ps))
    after["_wait_for"] = after.apply(
        lambda r: f"{r['vehicle_id']} is fixed" if r["_broken"] else f"{name_of(r['cause_road_id'])} opens", axis=1)
    after["original_vehicle"] = after["vehicle_id"]
    after["action"] = ""
    after["label_before"] = after["risk_label"]
    actions = []

    # ---- 1. Critical medical / perishable -> backup vehicle (chained trip).
    #         A broken-down vehicle can't be rerouted, so its High stops go to the backup too.
    backup = None
    backup_time, backup_pos, backup_jobs = NOW_MIN, None, []
    urgent = after[((after["risk_label"] == "Critical") & after["priority"].isin(["medical", "perishable"]))
                   | (after["_broken"] & after["risk_label"].isin(["Critical", "High"]))]
    for idx, row in urgent.sort_values("deadline_min").iterrows():
        source = vehicles.loc[row["original_vehicle"]]
        if backup is None:
            backup = nearest_backup(data, source["current_lat"], source["current_lng"])
            if backup is None:
                break
            backup_pos = (backup["current_lat"], backup["current_lng"])
        pickup = (source["current_lat"], source["current_lng"])
        to_pickup = haversine_km(*backup_pos, *pickup)
        to_customer = haversine_km(*pickup, row["lat"], row["lng"])
        eta = backup_time + travel_min(to_pickup) + HANDOVER_MIN + travel_min(to_customer) + DROP_MIN
        if eta > row["deadline_min"]:
            continue  # backup can't make it -> handled by reroute below
        idle_km = haversine_km(*backup_pos, *pickup)
        backup_time, backup_pos = eta, (row["lat"], row["lng"])
        backup_jobs.append(row["delivery_id"])
        eta_txt = min_to_hhmm(eta)

        saved = int(row["new_eta_min"] - eta)
        lateness = (f"misses its {row['deadline']} deadline by {-row['slack_min']} min"
                    if row["slack_min"] < 0 else f"has only {row['slack_min']} min slack")
        if len(backup_jobs) == 1:
            where = f"backup {backup['type']} {backup.name} ({backup['reg_no']}) is {idle_km:.1f} km away and idle"
        else:
            where = f"after its previous drop, backup {backup.name} is {idle_km:.1f} km from {row['original_vehicle']}"
        why = (f"{row['customer']} ({row['priority']}) {lateness}; {where}, "
               f"so it can collect the parcel from {row['original_vehicle']} and deliver by {eta_txt}.")
        actions.append({
            "action_type": "reassign",
            "target": f"delivery {row['delivery_id']}",
            "description": f"Move {row['delivery_id']} ({row['customer']}) from {row['original_vehicle']} "
                           f"to backup {backup.name} ({backup['driver']})",
            "expected_delay_saved_min": max(saved, 0),
            "extra_km": round((to_pickup + to_customer) * ROAD_FACTOR, 1),
            "deliveries_protected": [row["delivery_id"]],
            "why": why,
            "risk_label": row["risk_label"],
            "messages": [
                {"to": f"{backup['driver']} (driver, {backup.name})", "kind": "driver", "vehicle_id": backup.name,
                 "text": f"{backup['driver']}, please collect {row['delivery_id']} from "
                         f"{source['driver']} ({row['original_vehicle']}) and deliver to "
                         f"{row['customer']}, {row['address_area']} by {eta_txt}. "
                         f"Avoid {name_of(row['cause_road_id'])}."},
                {"to": f"{source['driver']} (driver, {row['original_vehicle']})", "kind": "driver",
                 "vehicle_id": row["original_vehicle"],
                 "text": f"{source['driver']}, hand {row['delivery_id']} ({row['customer']}) to {backup['driver']} "
                         f"in the backup {backup['type']} {backup.name} when they reach you. Continue with your other stops."},
                {"to": f"{row['customer']} ({row['customer_phone']})", "kind": "customer",
                 "customer": row["customer"], "phone": row["customer_phone"],
                 "text": _customer_sms(row, eta_txt, f"We've moved it to a dedicated vehicle ({backup['reg_no']}). ")},
            ],
        })
        after.loc[idx, ["vehicle_id", "new_eta_min", "action"]] = [backup.name, int(eta), "reassigned"]

    # ---- 2. Remaining Critical / High -> reroute their vehicle (one action per vehicle),
    #         with one detour per blocked road on its route
    pending = after[(after["action"] == "") & after["risk_label"].isin(["Critical", "High"]) & ~after["_broken"]]
    for vid in pending["original_vehicle"].unique():
        vehicle = vehicles.loc[vid]
        own = after[(after["original_vehicle"] == vid) & (after["action"] == "")]
        protected = own[own["risk_label"].isin(["Critical", "High"])]

        detours = {}  # blocked road -> (alternate road, extra km, extra min)
        for parts in own["parts"]:
            for part in parts:
                road = part["road_id"]
                if road in blocked_roads and road not in detours:
                    alt, extra_km = find_alternate_road(road, data, avoid=blocked_roads)
                    if alt is not None:
                        minutes = round(extra_km / alt["normal_speed_kmph"] * 60 + REROUTE_CONGESTION_MIN)
                        detours[road] = (alt, extra_km, minutes)
        if not detours:
            continue

        # blocked roads that share the same alternate are one detour, charged once
        by_alt = {}  # alternate road_id -> {"alt", "roads", "km", "min"}
        for road, (alt, km, minutes) in detours.items():
            group = by_alt.setdefault(alt["road_id"], {"alt": alt, "roads": [], "km": 0.0, "min": 0})
            group["roads"].append(road)
            group["km"], group["min"] = max(group["km"], km), max(group["min"], minutes)

        def rerouted_delay(parts):
            delay, cascade = 0, {}
            for p in parts:
                if p["road_id"] in detours:
                    alt_id = detours[p["road_id"]][0]["road_id"]
                    cascade[alt_id] = max(cascade.get(alt_id, 0), p["cascade_index"])
                else:
                    delay += p["delay_min"]
            return delay + sum(by_alt[a]["min"] + k * CASCADE_STEP_MIN for a, k in cascade.items())

        new_delays = own["parts"].apply(rerouted_delay)
        saved = int((own["delay_min"] - new_delays).clip(lower=0).max())
        total_km = round(sum(g["km"] for g in by_alt.values()), 1)
        total_min = sum(g["min"] for g in by_alt.values())
        via = " and ".join(g["alt"]["name"] for g in by_alt.values())
        around = " and ".join(f"{' and '.join(name_of(r) for r in g['roads'])} via {g['alt']['name']}"
                              for g in by_alt.values())
        blocked_text = " and ".join(f"{name_of(r)} ({TYPE_WORDS.get(road_type[r])})" for r in detours)
        avoid_text = f"avoid {blocked_text}. Take {via} instead"

        first = protected.iloc[0]
        lateness = (f"would miss its {first['deadline']} deadline by {-first['slack_min']} min"
                    if first["slack_min"] < 0 else f"has only {first['slack_min']} min slack")
        why = (f"{vid} ({vehicle['driver']}) still has {len(own)} stops behind the block; "
               f"{first['customer']} ({first['priority']}) {lateness}. Going via {via} adds "
               f"~{total_km} km (~{total_min} min) instead of waiting ~{int(first['delay_min'])} min.")
        stops = ", ".join(own.sort_values("stop_order")["delivery_id"])
        actions.append({
            "action_type": "reroute",
            "target": f"vehicle {vid}",
            "description": f"Reroute {vid} ({vehicle['reg_no']}) around {around}",
            "expected_delay_saved_min": saved,
            "extra_km": total_km,
            "deliveries_protected": own["delivery_id"].tolist(),
            "why": why,
            "risk_label": protected["risk_label"].iloc[0],
            "via_roads": list(by_alt),
            "messages": [
                {"to": f"{vehicle['driver']} (driver, {vid})", "kind": "driver", "vehicle_id": vid,
                 "text": f"{vehicle['driver']}, {avoid_text}. Next stops: {stops}."},
            ],
        })
        for idx, row in own.iterrows():
            delay = int(new_delays[idx])
            after.loc[idx, ["delay_min", "new_eta_min", "action"]] = [delay, int(row["eta_min"] + delay), "rerouted"]

    # ---- 3. Medium (and anything still unhandled) -> resequence / prioritise
    medium = after[(after["action"] == "") & (after["risk_label"] != "Low")
                   | ((after["action"] == "rerouted") & (after["label_before"] == "Medium"))]
    for idx, row in medium.iterrows():
        if row["action"] == "rerouted":
            saved, new_eta = 0, int(row["new_eta_min"])
            slack = int(row["deadline_min"] - new_eta)
            why = (f"{row['customer']} ({row['priority']}) still has {slack} min slack on "
                   f"{row['vehicle_id']}'s new route, so serve it after the time-critical stops.")
        else:
            saved = int(row["cascade_index"] * CASCADE_STEP_MIN)
            new_eta = int(row["new_eta_min"] - saved)
            slack = int(row["deadline_min"] - new_eta)
            why = (f"{row['customer']} ({row['priority']}) has {slack} min slack after the delay, so it doesn't "
                   f"need a vehicle swap; serving it first once {row['_wait_for']} keeps the cascade small.")
        actions.append({
            "action_type": "resequence",
            "target": f"delivery {row['delivery_id']}",
            "description": f"Prioritise {row['delivery_id']} ({row['customer']}) in {row['vehicle_id']}'s sequence",
            "expected_delay_saved_min": saved,
            "extra_km": 0.0,
            "deliveries_protected": [row["delivery_id"]],
            "why": why,
            "risk_label": row["risk_label"],
            "messages": [{"to": f"{row['customer']} ({row['customer_phone']})", "kind": "customer",
                          "customer": row["customer"], "phone": row["customer_phone"],
                          "text": _customer_sms(row, min_to_hhmm(new_eta))}],
        })
        if row["action"] == "":
            after.loc[idx, ["new_eta_min", "action"]] = [new_eta, "resequenced"]

    # ---- 4. Low -> reschedule + notify
    low = after[(after["action"] == "") | ((after["action"] == "rerouted") & (after["label_before"] == "Low"))]
    for idx, row in low.iterrows():
        eta = int(row["new_eta_min"])
        why = (f"{row['customer']} is low risk ({row['slack_min']} min slack, {row['priority']}); "
               f"a heads-up message is enough, no vehicle change needed.")
        actions.append({
            "action_type": "reschedule_notify",
            "target": f"delivery {row['delivery_id']}",
            "description": f"Notify {row['customer']} of new ETA {min_to_hhmm(eta)}",
            "expected_delay_saved_min": 0,
            "extra_km": 0.0,
            "deliveries_protected": [row["delivery_id"]],
            "why": why,
            "risk_label": row["risk_label"],
            "messages": [{"to": f"{row['customer']} ({row['customer_phone']})", "kind": "customer",
                          "customer": row["customer"], "phone": row["customer_phone"],
                          "text": _customer_sms(row, min_to_hhmm(eta))}],
        })
        if eta > row["deadline_min"]:  # customer agrees a new slot
            new_deadline = eta + RESCHEDULE_BUFFER_MIN
            after.loc[idx, ["deadline_min", "deadline"]] = [new_deadline, min_to_hhmm(new_deadline)]
        if row["action"] == "":
            after.loc[idx, "action"] = "notified"

    # ---- after-state, rescored
    after["new_eta_min"] = after["new_eta_min"].astype(int)
    after["new_eta"] = after["new_eta_min"].apply(min_to_hhmm)
    after["delay_min"] = (after["new_eta_min"] - after["eta_min"]).clip(lower=0)
    after["slack_min"] = (after["deadline_min"] - after["new_eta_min"]).astype(int)
    after["will_miss"] = after["slack_min"] < 0
    after["off_route"] = after["action"] == "reassigned"
    after = score_risk(after.drop(columns=["risk_score", "risk_label", "reason", "_cause", "_broken", "_wait_for"]),
                       disruptions)

    if polish:
        for action, why in zip(actions, polish_whys([a["why"] for a in actions])):
            action["why"] = why

    before_after = {
        "misses_before": int(impact["will_miss"].sum()),
        "misses_after": int(after["will_miss"].sum()),
        "delay_before": int(impact["delay_min"].sum()),
        "delay_after": int(after["delay_min"].sum()),
        "critical_before": int((impact["risk_label"] == "Critical").sum()),
        "critical_after": int((after["risk_label"] == "Critical").sum()),
    }
    order = {"reassign": 0, "reroute": 1, "resequence": 2, "reschedule_notify": 3}
    actions.sort(key=lambda a: order[a["action_type"]])
    return actions, before_after, after


if __name__ == "__main__":
    from modules.data_loader import load_all
    from modules.impact import compute_impact
    from modules.parser import parse_disruption

    data = load_all()
    for text in ["Accident near Avinashi Road, road blocked for 2 hours",
                 "Murugan vandi breakdown aachu near Race Course"]:
        demo = parse_disruption(text, data, use_llm=False)
        risk = score_risk(compute_impact(demo, data)[0], demo)
        actions, before_after, after = recommend(risk, demo, data, polish=False)
        print(f"\n=== {text}")
        for a in actions:
            print(f"[{a['action_type']}] {a['description']} | saved {a['expected_delay_saved_min']} min, "
                  f"+{a['extra_km']} km\n    why: {a['why']}")
        print(before_after)
        print(after[["delivery_id", "vehicle_id", "action", "new_eta", "deadline", "slack_min", "risk_label"]]
              .to_string(index=False))

    # two disruptions at once: reroutes must not use the other blocked road
    both = [parse_disruption(t, data, use_llm=False) for t in
            ["Accident near Avinashi Road, road blocked for 2 hours", "Heavy rain flooding at Trichy Road, 45 mins"]]
    actions, before_after, _ = recommend(score_risk(compute_impact(both, data)[0], both), both, data, polish=False)
    print("\n=== Accident + rain")
    for a in actions:
        if a["action_type"] in ("reassign", "reroute"):
            print(f"[{a['action_type']}] {a['description']} | +{a['extra_km']} km")
    print(before_after)
    assert not any(set(a.get("via_roads", [])) & {"R1", "R2"} for a in actions)
    print("recommender OK")
