"""The operator's brain.

analyse()  – impact + risk + recovery plan for a reported issue, explained the way a senior
             dispatcher would say it.
accept()   – apply the plan everywhere: deliveries, ETAs, routes, partner inboxes, customer SMS.
reject()   – close the issue and tell the reporter why.
"""
import json
import re

from modules import store
from modules.data_loader import min_to_hhmm
from modules.impact import NO_RIPPLE_TYPES, compute_impact
from modules.issues import set_location, summarize, type_label
from modules.parser import call_llm, llm_available
from modules.recommender import recommend
from modules.risk import score_risk

RISK_COLUMNS = ["delivery_id", "customer", "address_area", "priority", "vehicle_id", "road_id", "road_name",
                "planned_eta", "new_eta", "deadline", "delay_min", "slack_min", "will_miss", "risk_score",
                "risk_label", "reason", "lat", "lng", "stop_order", "cascade_index", "disruption_ids"]
AFTER_COLUMNS = ["delivery_id", "customer", "priority", "vehicle_id", "original_vehicle", "action", "planned_eta",
                 "new_eta", "deadline", "slack_min", "will_miss", "risk_label"]
REATTEMPT_GAP_MIN = 20
PRIORITY_ORDER = ["medical", "perishable", "express", "standard"]


def _records(df, columns):
    """DataFrame -> plain JSON-safe records (numpy numbers become normal numbers)."""
    return json.loads(df[[c for c in columns if c in df.columns]].to_json(orient="records"))


def to_disruption(problem):
    keys = ["type", "road_id", "road_name", "severity", "duration_min", "vehicle_id", "place"]
    return {k: problem.get(k) for k in keys}


# ---------------------------------------------------------------- analyse
def analyse(issue_id):
    """Build (or rebuild) the AI plan for an issue and store it. Returns the plan."""
    issue = store.get_issue(issue_id)
    problem = issue["problem"]
    branch = issue["branch_id"]
    data = store.snapshot(branch)  # same-branch routes, partners and backup vehicles only

    if problem.get("needs_location"):
        plan = {"kind": "needs_location", "actions": [], "risk": [], "after": [],
                "note": "The report doesn't say where this is. Pick the road and the plan will be ready."}
    elif problem["type"] in NO_RIPPLE_TYPES:
        plan = _single_stop_plan(problem, data)
    else:
        plan = _ripple_plan(problem, data, branch)

    plan["issue_id"] = issue_id
    plan["created_at"] = store.now_stamp()
    store.update_issue(issue_id, plan=plan, status="analysed" if plan["kind"] != "needs_location" else "new")
    if plan["kind"] != "needs_location":
        store.log_event("ai", f"AI plan for #{issue_id}: {plan['headline']}", issue_id, branch_id=branch)
    return plan


def _ripple_plan(problem, data, branch_id=None):
    disruption = to_disruption(problem)
    impact, summary = compute_impact(disruption, data)
    risk = score_risk(impact, disruption)
    # roads already blocked by earlier accepted issues must not be used for detours
    actions, before_after, after = recommend(risk, [*store.active_disruptions(branch_id), disruption], data)
    counts = risk["risk_label"].value_counts().to_dict() if len(risk) else {}
    if len(risk):
        headline = (f"{summary['affected_deliveries']} deliveries on {len(summary['affected_vehicles'])} vehicles hit · "
                    f"missed deadlines {before_after['misses_before']} → {before_after['misses_after']} with this plan")
    else:
        headline = "No planned delivery is affected"
    plan = {
        "kind": "ripple", "disruption": disruption, "headline": headline,
        "summary": {k: summary[k] for k in ["affected_roads", "affected_vehicles", "affected_deliveries",
                                            "total_delay_min", "predicted_misses", "message"]},
        "risk_counts": counts, "risk": _records(risk, RISK_COLUMNS) if len(risk) else [],
        "actions": actions, "before_after": before_after,
        "after": _records(after, AFTER_COLUMNS) if len(after) else [],
        "via_roads": sorted({r for a in actions for r in a.get("via_roads", [])}),
    }
    plan["note"] = dispatcher_note(problem, plan, data)
    return plan


def _single_stop_plan(problem, data):
    deliveries = data["deliveries"]
    target = deliveries[deliveries["delivery_id"] == problem.get("delivery_id")]
    if target.empty:
        return {"kind": "single_stop", "headline": "No pending stop to re-attempt", "actions": [], "risk": [],
                "after": [], "before_after": {}, "note": "This partner has no pending stops left, nothing to change."}
    row = target.iloc[0]
    own = deliveries[deliveries["vehicle_id"] == row["vehicle_id"]]
    new_eta = int(own["eta_min"].max()) + REATTEMPT_GAP_MIN
    late = new_eta > row["deadline_min"]
    driver = problem.get("reporter_name", "the driver")
    action = {
        "title": f"Re-attempt {row['delivery_id']} later",
        "why_short": f"Customer not reachable.\n{'Misses ' + row['deadline'] + ', ask for a new slot.' if late else 'Still fits before ' + row['deadline'] + '.'}",
        "impact_short": f"New ETA {min_to_hhmm(new_eta)}",
        "action_type": "reschedule_notify", "target": f"delivery {row['delivery_id']}",
        "description": f"Re-attempt {row['customer']} at the end of {driver}'s route (~{min_to_hhmm(new_eta)})",
        "why": (f"{row['customer']} isn't reachable now. Trying again after the other stops costs nothing; "
                f"{'the deadline ' + row['deadline'] + ' will be missed, so we ask the customer for a new slot.' if late else 'it still fits before the ' + row['deadline'] + ' deadline.'}"),
        "expected_delay_saved_min": 0, "extra_km": 0.0, "deliveries_protected": [row["delivery_id"]],
        "risk_label": "Medium" if late else "Low",
        "messages": [
            {"to": f"{driver} (driver, {row['vehicle_id']})", "kind": "driver", "vehicle_id": row["vehicle_id"],
             "text": f"{driver}, skip {row['customer']} for now and continue. Re-attempt at ~{min_to_hhmm(new_eta)}."},
            {"to": f"{row['customer']} ({row['customer_phone']})", "kind": "customer", "customer": row["customer"],
             "phone": row["customer_phone"],
             "text": f"Hi {row['customer']}, our partner could not reach you. We will try again at about "
                     f"{min_to_hhmm(new_eta)}. Reply with a better time if needed. – DEPORT Logistics"},
        ],
    }
    return {
        "kind": "single_stop", "headline": f"1 stop to re-attempt: {row['customer']}", "actions": [action],
        "risk": [], "before_after": {}, "via_roads": [],
        "after": [{"delivery_id": row["delivery_id"], "vehicle_id": row["vehicle_id"], "new_eta": min_to_hhmm(new_eta),
                   "deadline": row["deadline"], "action": "reattempt", "stop_order": int(own["stop_order"].max()) + 1}],
        "note": (f"{driver} couldn't reach {row['customer']}. Keep the route moving and re-attempt around "
                 f"{min_to_hhmm(new_eta)}; the customer gets a message now."),
    }


# ---------------------------------------------------------------- human-style explanation
def dispatcher_note(problem, plan, data):
    """2–4 short sentences a senior dispatcher would say. Template first, LLM polish if available."""
    template = _template_note(problem, plan, data)
    if not llm_available():
        return template
    prompt = ("You are a calm, experienced delivery dispatcher in Coimbatore talking to the operations manager. "
              "Rewrite the note below in 2-4 short, plain sentences. Keep every number, name, vehicle id and "
              "time exactly. Do not use he/she pronouns. No preamble.\n\nNOTE:\n" + template)
    try:
        polished = call_llm(prompt).strip().strip('"')
    except Exception:
        return template
    numbers = set(re.findall(r"\d+(?:[.:]\d+)?", template))
    return polished if polished and numbers <= set(re.findall(r"\d+(?:[.:]\d+)?", polished)) else template


def _template_note(problem, plan, data):
    summary, before_after = plan["summary"], plan["before_after"]
    where = problem.get("road_name") or "the route"
    hours = int(problem.get("duration_min") or 0)
    lasting = f" for about {hours // 60} h {hours % 60} min".replace(" 0 min", "") if hours >= 60 else (
        f" for about {hours} min" if hours else "")
    who = problem.get("reporter_name", "A partner")
    if not plan["risk"]:
        return (f"{who} reports {type_label(problem['type']).lower()} on {where}{lasting}. None of today's "
                f"pending deliveries use that road, so no action is needed; keep an eye on it.")
    sentences = [f"{who} reports {type_label(problem['type']).lower()} on {where}{lasting}. "
                 f"That puts {summary['affected_deliveries']} deliveries on "
                 f"{len(summary['affected_vehicles'])} vehicles at risk, and {summary['predicted_misses']} would "
                 f"miss their deadline."]
    late = [r for r in plan["risk"] if r["slack_min"] < 0]
    if late:  # a medical parcel worries a dispatcher more than a slightly later express one
        worst = min(late, key=lambda r: (PRIORITY_ORDER.index(r["priority"]) if r["priority"] in PRIORITY_ORDER
                                         else 9, r["slack_min"]))
        sentences.append(f"The real worry is {worst['customer']} ({worst['priority']}), "
                         f"{-worst['slack_min']} min late if we do nothing.")
    reassigns = [a for a in plan["actions"] if a["action_type"] == "reassign"]
    reroutes = [a for a in plan["actions"] if a["action_type"] == "reroute"]
    moves = []
    if reassigns:
        backup = reassigns[0]["description"].split(" to backup ")[-1]
        ids = ", ".join(a["deliveries_protected"][0] for a in reassigns)
        moves.append(f"send the backup {backup} to pick up {ids}")
    if reroutes:
        vehicles = ", ".join(a["target"].replace("vehicle ", "") for a in reroutes)
        moves.append(f"detour {vehicles} around {where}")
    if moves:
        move_text = " and ".join(moves)
        sentences.append(move_text[0].upper() + move_text[1:] + "; everyone else has enough slack, so we just "
                         "keep customers informed.")
    if before_after:
        sentences.append(f"With this plan missed deadlines go from {before_after['misses_before']} to "
                         f"{before_after['misses_after']}.")
    return " ".join(sentences)


# ---------------------------------------------------------------- decisions
def _issue_in_branch(issue_id, branch_id):
    """The issue, or PermissionError when a branch admin reaches for another branch's issue."""
    issue = store.get_issue(issue_id, branch_id)
    if issue is None:
        raise PermissionError(f"Issue #{issue_id} is not in your branch")
    return issue


def accept(issue_id, decided_by="Manager", branch_id=None):
    """Apply the plan to the issue's own branch only. Returns a short summary of what changed.

    branch_id: the decider's branch (from the session); another branch's issue raises PermissionError.
    """
    issue = _issue_in_branch(issue_id, branch_id)
    branch = issue["branch_id"]
    plan = issue.get("plan")
    if not plan or plan["kind"] == "needs_location":
        raise ValueError("This issue has no plan yet")
    # one transaction: deliveries, routes, messages, the block, the issue and the log change together or not at all
    with store.transaction():
        partner_by_vehicle = {p["vehicle_id"]: p for p in store.partners_df(branch).to_dict("records")}
        changed = {"deliveries": 0, "partners_told": set(), "customers_told": 0}

        # 1) deliveries: new vehicle, ETA, deadline, stop order
        backup_stops = {}
        for row in plan["after"]:
            fields = {"vehicle_id": row["vehicle_id"], "planned_eta": row["new_eta"], "deadline": row["deadline"],
                      "note": row["action"]}
            if row["action"] == "reassigned":
                backup_stops.setdefault(row["vehicle_id"], []).append(row)
            if "stop_order" in row:
                fields["stop_order"] = row["stop_order"]
            store.update_delivery(row["delivery_id"], branch_id=branch, **fields)
            changed["deliveries"] += 1
        for vehicle_id, rows in backup_stops.items():  # backup van: stops in ETA order
            for order, row in enumerate(sorted(rows, key=lambda r: r["new_eta"]), start=1):
                store.update_delivery(row["delivery_id"], branch_id=branch, stop_order=order)
            partner = partner_by_vehicle.get(vehicle_id)
            if partner and partner["status"] != "on_duty":
                store.set_partner_status(partner["partner_id"], "on_duty")

        # 2) routes: blocked road replaced by the detour
        blocked = (plan.get("disruption") or {}).get("road_id")
        vehicles = store.vehicles_df(branch).set_index("vehicle_id")
        for action in plan["actions"]:
            if action["action_type"] == "reroute" and blocked and action.get("via_roads"):
                vid = action["target"].replace("vehicle ", "")
                route = [action["via_roads"][0] if r == blocked else r for r in vehicles.loc[vid, "route_roads"]]
                store.set_route(vid, list(dict.fromkeys(route)), branch_id=branch)

        # 3) messages: partner inboxes and customer SMS
        for action in plan["actions"]:
            for message in action.get("messages", []):
                if message.get("kind") == "driver":
                    partner = partner_by_vehicle.get(message.get("vehicle_id"))
                    if partner:
                        store.add_message(message["text"], to_partner=partner["partner_id"], issue_id=issue_id,
                                          branch_id=branch)
                        changed["partners_told"].add(partner["partner_id"])
                elif message.get("kind") == "customer":
                    store.add_message(message["text"], to_customer=message.get("customer"), to_phone=message.get("phone"),
                                      channel="sms", issue_id=issue_id, branch_id=branch)
                    changed["customers_told"] += 1
        reporter = issue.get("partner_id")
        if reporter and reporter not in changed["partners_told"] and reporter in {p["partner_id"] for p in partner_by_vehicle.values()}:
            store.add_message(f"Thanks, your report was handled: {plan['headline']}.", to_partner=reporter,
                              issue_id=issue_id, branch_id=branch)

        # 4) the road stays blocked for future plans; close the issue; refresh other open plans
        if plan["kind"] == "ripple" and plan.get("disruption", {}).get("road_id") and \
                plan["disruption"]["type"] not in ("breakdown",) + NO_RIPPLE_TYPES:
            store.add_disruption(issue_id, plan["disruption"], branch_id=branch)
        store.update_issue(issue_id, status="accepted", decided_at=store.now_stamp(), decision_note=f"Accepted by {decided_by}")
        text = (f"{decided_by} accepted the plan for #{issue_id}: {changed['deliveries']} deliveries updated, "
                f"{len(changed['partners_told'])} partners and {changed['customers_told']} customers notified")
        store.log_event("decision", text, issue_id, branch_id=branch)
    for other in store.list_issues(("analysed",), branch_id=branch):
        analyse(other["issue_id"])  # the branch changed, so its other plans must too
    return text


def reject(issue_id, reason="Not needed", decided_by="Manager", branch_id=None):
    issue = _issue_in_branch(issue_id, branch_id)
    store.update_issue(issue_id, status="rejected", decided_at=store.now_stamp(), decision_note=reason)
    if issue.get("partner_id"):
        store.add_message(f"Your report #{issue_id} was reviewed: {reason}. Continue as planned.",
                          to_partner=issue["partner_id"], issue_id=issue_id, branch_id=issue["branch_id"])
    store.log_event("decision", f"{decided_by} rejected #{issue_id}: {reason}", issue_id, branch_id=issue["branch_id"])


def edit_problem(issue_id, branch_id=None, **changes):
    """Branch admin corrects what the AI understood (type, road, severity, duration), then re-plans."""
    issue = _issue_in_branch(issue_id, branch_id)
    problem = dict(issue["problem"])
    if "road_id" in changes and changes["road_id"]:
        problem = set_location(problem, changes.pop("road_id"), store.snapshot(issue["branch_id"]))
    problem.update({k: v for k, v in changes.items() if v is not None})
    problem["summary"] = summarize(problem)
    store.update_issue(issue_id, problem=problem, summary=problem["summary"])
    store.log_event("edit", f"Issue #{issue_id} corrected: {problem['summary']}", issue_id,
                    branch_id=issue["branch_id"])
    return analyse(issue_id)


def mark_delivered(delivery_id, partner_name="Partner", branch_id=None):
    store.update_delivery(delivery_id, branch_id=branch_id, status="delivered")
    store.log_event("delivery", f"{partner_name} delivered {delivery_id}", branch_id=branch_id)


def kpis(branch_id=None):
    """Numbers for the branch admin's top bar (one branch)."""
    partners = store.partners_df(branch_id)
    deliveries = store.deliveries_df(branch_id=branch_id)
    open_issues = store.list_issues(store.OPEN_ISSUE_STATUSES, branch_id=branch_id)
    at_risk, labels = set(), {}
    for issue in open_issues:
        for row in (issue.get("plan") or {}).get("risk", []):
            labels.setdefault(row["delivery_id"], row["risk_label"])
            if row["risk_label"] in ("Critical", "High"):
                at_risk.add(row["delivery_id"])
    accepted = store.list_issues(("accepted",), branch_id=branch_id)
    saved = sum((i["plan"].get("before_after") or {}).get("misses_before", 0) -
                (i["plan"].get("before_after") or {}).get("misses_after", 0) for i in accepted if i.get("plan"))
    pending = deliveries[~deliveries["status"].isin(["delivered", "failed"])]
    vehicles = store.vehicles_df(branch_id)
    return {
        "on_duty": int((partners["status"] == "on_duty").sum()), "partners": len(partners),
        "deliveries": len(deliveries), "delivered": int((deliveries["status"] == "delivered").sum()),
        "at_risk": len(at_risk), "open_issues": len(open_issues), "deadlines_saved": int(saved),
        "critical": sum(1 for v in labels.values() if v == "Critical"),
        "delayed": sum(1 for v in labels.values() if v in ("High", "Medium")),
        "free_vehicles": int((~vehicles["vehicle_id"].isin(pending["vehicle_id"])).sum()),
    }


if __name__ == "__main__":
    import os
    import tempfile
    from pathlib import Path

    from modules import issues

    os.environ["RIPPLE_DB"] = str(Path(tempfile.mkdtemp()) / "ops.db")
    store.init_db()
    seen = issues.preview("DP101", text="Avinashi road la accident, full block, rendu mani neram aagum")
    issue_id = issues.submit("DP101", seen["problem"], transcript=seen["transcript"])
    plan = store.get_issue(issue_id)["plan"]
    print("HEADLINE:", plan["headline"])
    print("NOTE:", plan["note"])
    print("KPIs before:", kpis())
    print(accept(issue_id))
    print("KPIs after:", kpis())
    print("Lakshmi's inbox:", [m["text"] for m in store.messages_for("DP106")])
    print("Murugan's inbox:", [m["text"][:70] for m in store.messages_for("DP101")])
    print("V1 route now:", store.vehicles_df().set_index("vehicle_id").loc["V1", "route_roads"])
    print("operations OK")
