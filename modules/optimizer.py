"""Re-optimise a branch's routes after a disruption with Google OR-Tools – a vehicle routing problem with time
windows (deadlines) and capacities. No Streamlit imports. Optional: without OR-Tools the rule-based plan stays.

Scope (the affected branch only): the vehicles hit by the disruption, the branch's backup vehicles and nearby
partners with spare capacity. Stops of hit (or broken-down) vehicles may move to any of them; a nearby partner keeps
their own stops and may take extra ones. Parcels only go on vehicles they fit (bike = small …).

Time model: each vehicle starts now from where it is. Driving minutes come from the cached OSRM leg when there is
one, else the straight line × road factor at city speed (same as the rule-based plan). No stop is served before its
planned ETA (the customer expects it then), so untouched routes keep their times. A stop beyond a blocked road costs
the detour once; a parcel moved to another vehicle costs the trip to meet its current driver plus the handover
(once per pickup).
Costs: driving minutes, plus 10 per parcel moved to another vehicle (moves must be worth it); every minute after a
deadline costs by priority (medical highest); a stop may be left out only at a very high cost, again by priority –
so when not everything fits, medical is served first.
Search: cheapest-arc start + local search (≤ 5 s); "thorough" adds guided local search for the full time limit.
"""
import time
from dataclasses import dataclass, field

from modules.assign import FITS, MAX_STOPS
from modules.data_loader import NOW_MIN, haversine_km, min_to_hhmm
from modules.recommender import DROP_MIN, HANDOVER_MIN, REROUTE_CONGESTION_MIN, ROAD_FACTOR, find_alternate_road

try:  # optional dependency
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
except ImportError:  # pragma: no cover - exercised only without OR-Tools
    pywrapcp = routing_enums_pb2 = None

SPEED_KMPH = 25           # same city speed as the rule-based recommender
NEARBY_KM = 6.0           # partners this close to a hit stop may help
TIME_LIMIT_S = 5
HORIZON_MIN = 24 * 60
LATE_COST = {"medical": 20, "perishable": 12, "express": 6, "standard": 3}  # per minute late (1 = 1 min driving)
DROP_COST = {"medical": 100_000, "perishable": 50_000, "express": 20_000, "standard": 10_000}
MOVE_COST = 10            # per parcel given to another vehicle (in driving minutes)
NOT_A_BLOCK = ("breakdown", "requirement_change", "customer_unavailable")


def available():
    """True when OR-Tools is installed."""
    return pywrapcp is not None


@dataclass
class Vehicle:
    """A vehicle the optimiser may use: start point and capacity in stops."""

    vehicle_id: str
    kind: str
    lat: float
    lng: float
    capacity: int
    driver: str = ""


@dataclass
class Stop:
    """One delivery: where, by when, who holds the parcel now, and what is in the way."""

    delivery_id: str
    lat: float
    lng: float
    deadline_min: int
    planned_min: int
    priority: str = "standard"
    size: str = "small"
    owner: str | None = None      # vehicle that holds the parcel now
    pinned: bool = False          # must stay with its owner (a nearby partner's own stop)
    needs: frozenset = frozenset()  # blocked roads it lies beyond
    affected: bool = False
    customer: str = ""
    phone: str = ""


@dataclass
class Problem:
    """Vehicles, stops and the detour (km, minutes) to get past each blocked road (via = the alternate road)."""

    vehicles: list
    stops: list
    detours: dict = field(default_factory=dict)
    via: dict = field(default_factory=dict)
    legs: dict = field(default_factory=dict)  # {(lat,lng),(lat,lng)} -> km from cached OSRM legs


# ---------------------------------------------------------------- distances
def _km(problem, a, b):
    return problem.legs.get((a, b)) or haversine_km(*a, *b) * ROAD_FACTOR


def _drive(problem, a, b):
    return _km(problem, a, b) / SPEED_KMPH * 60


def _owner_point(problem, stop):
    owner = next((v for v in problem.vehicles if v.vehicle_id == stop.owner), None)
    return (owner.lat, owner.lng) if owner else None


def _leg(problem, vehicle, prev, stop, owner_points):
    """(minutes, km) from prev (a Stop or None = the vehicle's start) to stop, for this vehicle."""
    here = (prev.lat, prev.lng) if prev else (vehicle.lat, vehicle.lng)
    there = (stop.lat, stop.lng)
    moved = stop.owner and stop.owner != vehicle.vehicle_id
    same_pickup = moved and prev is not None and prev.owner == stop.owner
    if moved and not same_pickup and owner_points.get(stop.owner):
        meet = owner_points[stop.owner]
        drive = _drive(problem, here, meet) + _drive(problem, meet, there)
        km = _km(problem, here, meet) + _km(problem, meet, there)
        handover = HANDOVER_MIN
    else:
        drive, km, handover = _drive(problem, here, there), _km(problem, here, there), 0.0
    detour_min = detour_km = 0.0
    for road in stop.needs - (prev.needs if prev else frozenset()):
        km_extra, min_extra = problem.detours.get(road, (0.0, 0.0))
        detour_km, detour_min = detour_km + km_extra, detour_min + min_extra
    service = DROP_MIN if prev else 0.0
    return drive + service + handover + detour_min, km + detour_km


def route_eval(problem, vehicle, stops, detour=True):
    """Walk one vehicle's stops in order: ([(stop, arrival minute)], km). Never earlier than a stop's plan."""
    owner_points = {s.owner: _owner_point(problem, s) for s in stops if s.owner}
    clock, km, prev, out = float(NOW_MIN), 0.0, None, []
    for stop in stops:
        minutes, leg_km = _leg(problem, vehicle, prev, stop if detour else _no_needs(stop), owner_points)
        clock, km = max(clock + minutes, float(stop.planned_min)), km + leg_km
        out.append((stop, clock))
        prev = stop if detour else _no_needs(stop)
    return out, km


def _no_needs(stop):
    return Stop(**{**stop.__dict__, "needs": frozenset()})


# ---------------------------------------------------------------- the solver
def solve(problem, time_limit_s=TIME_LIMIT_S, thorough=False):
    """Run OR-Tools. Returns {status, routes {vehicle_id: [(Stop, arrival)]}, dropped [Stop], seconds}."""
    if not available():
        raise RuntimeError("OR-Tools is not installed")
    vehicles, stops = problem.vehicles, problem.stops
    n_vehicles, end = len(vehicles), len(vehicles)
    first_stop = end + 1
    manager = pywrapcp.RoutingIndexManager(first_stop + len(stops), n_vehicles, list(range(n_vehicles)),
                                           [end] * n_vehicles)
    routing = pywrapcp.RoutingModel(manager)

    def stop_of(node):
        return stops[node - first_stop] if node >= first_stop else None

    callbacks = []
    owner_points = {s.owner: _owner_point(problem, s) for s in stops if s.owner}
    for v, vehicle in enumerate(vehicles):
        times, costs = {}, {}
        for i in [v, *range(first_stop, first_stop + len(stops))]:
            for j in range(first_stop, first_stop + len(stops)):
                if i != j:
                    minutes = int(round(_leg(problem, vehicle, stop_of(i), stop_of(j), owner_points)[0]))
                    times[i, j] = minutes
                    costs[i, j] = minutes + (MOVE_COST if stop_of(j).owner != vehicle.vehicle_id else 0)

        def transit(from_index, to_index, table=times):
            return table.get((manager.IndexToNode(from_index), manager.IndexToNode(to_index)), 0)

        def cost(from_index, to_index, table=costs):
            return table.get((manager.IndexToNode(from_index), manager.IndexToNode(to_index)), 0)

        callbacks.append(routing.RegisterTransitCallback(transit))
        routing.SetArcCostEvaluatorOfVehicle(routing.RegisterTransitCallback(cost), v)

    routing.AddDimensionWithVehicleTransits(callbacks, HORIZON_MIN, HORIZON_MIN, False, "Time")  # waiting allowed
    clock = routing.GetDimensionOrDie("Time")
    demand = routing.RegisterUnaryTransitCallback(lambda index: 1 if manager.IndexToNode(index) >= first_stop else 0)
    routing.AddDimensionWithVehicleCapacity(demand, 0, [v.capacity for v in vehicles], True, "Load")
    for v in range(n_vehicles):
        clock.CumulVar(routing.Start(v)).SetRange(NOW_MIN, NOW_MIN)

    for k, stop in enumerate(stops):
        index = manager.NodeToIndex(first_stop + k)
        allowed = [v for v, vehicle in enumerate(vehicles)
                   if (vehicle.vehicle_id == stop.owner if stop.pinned else stop.size in FITS.get(vehicle.kind, ()))]
        routing.VehicleVar(index).SetValues([-1, *allowed])  # -1 = left out (only via the disjunction below)
        clock.CumulVar(index).SetMin(int(stop.planned_min))      # not before the customer expects it
        clock.SetCumulVarSoftUpperBound(index, int(stop.deadline_min), LATE_COST.get(stop.priority, 3))
        routing.AddDisjunction([index], DROP_COST.get(stop.priority, 10_000))

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    if thorough:
        params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.FromMilliseconds(int(time_limit_s * 1000))
    started = time.perf_counter()
    solution = routing.SolveWithParameters(params)
    seconds = round(time.perf_counter() - started, 3)
    if solution is None:
        return {"status": "no solution", "routes": {}, "dropped": list(stops), "seconds": seconds}

    routes, served = {}, set()
    for v, vehicle in enumerate(vehicles):
        index, ordered = routing.Start(v), []
        while not routing.IsEnd(index):
            stop = stop_of(manager.IndexToNode(index))
            if stop:
                ordered.append(stop)
                served.add(stop.delivery_id)
            index = solution.Value(routing.NextVar(index))
        routes[vehicle.vehicle_id] = route_eval(problem, vehicle, ordered)[0]  # same clock as the comparison
    dropped = [s for s in stops if s.delivery_id not in served]
    return {"status": "ok", "routes": routes, "dropped": dropped, "seconds": seconds}


# ---------------------------------------------------------------- from the app's data
def build_problem(data, impact, disruptions, partners):
    """Problem for one branch from its snapshot, the impact rows and the disruptions (see the module docstring)."""
    vehicles = data["vehicles"].set_index("vehicle_id")
    deliveries = data["deliveries"]
    partner_of = {p["vehicle_id"]: p for p in partners}
    blocked = {d["road_id"] for d in disruptions if d.get("road_id") and d.get("type") not in NOT_A_BLOCK}
    broken = {d["vehicle_id"] for d in disruptions if d.get("type") == "breakdown" and d.get("vehicle_id")}
    hit = set(impact["vehicle_id"]) if len(impact) else set()
    needs = {r["delivery_id"]: frozenset(p["road_id"] for p in r["parts"] if p.get("road_id") in blocked)
             for r in impact.to_dict("records")}
    hit_points = list(zip(impact["lat"], impact["lng"])) if len(impact) else []

    fleet, pinned_owners = [], set()
    for vid, v in vehicles.iterrows():
        partner = partner_of.get(vid, {})
        off = partner.get("status") in ("on_break", "off_duty") or not partner.get("account_active", True)
        if vid in broken or off:
            continue
        own = deliveries[deliveries["vehicle_id"] == vid]
        near = min((haversine_km(v["current_lat"], v["current_lng"], *p) for p in hit_points), default=99)
        if vid in hit or v["status"] == "backup":
            pass
        elif v["status"] == "active" and len(own) < MAX_STOPS.get(v["type"], 8) and near <= NEARBY_KM:
            pinned_owners.add(vid)
        else:
            continue
        fleet.append(Vehicle(vid, v["type"], float(v["current_lat"]), float(v["current_lng"]),
                             MAX_STOPS.get(v["type"], 8), driver=partner.get("name") or str(v.get("driver") or vid)))

    stops, affected = [], set(needs)
    for d in deliveries.to_dict("records"):
        owner = d["vehicle_id"]
        if owner not in hit and owner not in broken and owner not in pinned_owners:
            continue
        stops.append(Stop(d["delivery_id"], float(d["lat"]), float(d["lng"]), int(d["deadline_min"]),
                          int(d["eta_min"]), d.get("priority") or "standard", d.get("package_size") or "small",
                          owner, owner in pinned_owners, needs.get(d["delivery_id"], frozenset()),
                          d["delivery_id"] in affected, d.get("customer", ""), d.get("customer_phone", "")))

    detours, via = {}, {}
    for road in blocked:
        alt, extra_km = find_alternate_road(road, data, avoid=blocked)
        minutes = extra_km / alt["normal_speed_kmph"] * 60 + REROUTE_CONGESTION_MIN if alt is not None else 30.0
        detours[road] = (round(extra_km, 2), round(minutes, 1))
        if alt is not None:
            via[road] = alt.name
    return Problem(fleet, stops, detours, via, legs=_cached_legs(stops, fleet))


def _cached_legs(stops, fleet):
    """Driving distances of the cached OSRM legs (vehicle -> next stop) as {(a, b): km}."""
    from modules import geometry, store

    shapes = store.route_geometry()
    points = [(v.lat, v.lng) for v in fleet] + [(s.lat, s.lng) for s in stops]
    legs = {}
    for a in points:
        for b in points:
            line = shapes.get(geometry.leg_key(a, b)) if a != b else None
            if line and len(line) > 1:
                legs[a, b] = sum(haversine_km(*p, *q) for p, q in zip(line, line[1:]))
    return legs


# ---------------------------------------------------------------- the optimised plan and the comparison
def optimise(data, impact, disruptions, partners, rule_plan, time_limit_s=TIME_LIMIT_S, thorough=False):
    """The optimised alternative to the rule-based plan: routes, moves, messages and before / rules / optimised
    numbers (missed deadlines, total delay, total km). {"available": False, ...} without OR-Tools."""
    if not available():
        return {"available": False, "note": "Install OR-Tools (pip install ortools) for the optimised plan."}
    if impact is None or not len(impact):
        return {"available": True, "status": "nothing to optimise", "routes": {}, "comparison": {}}
    problem = build_problem(data, impact, disruptions, partners)
    result = solve(problem, time_limit_s, thorough)
    by_vehicle = {v.vehicle_id: v for v in problem.vehicles}
    names = {v.vehicle_id: v.driver for v in problem.vehicles}
    routes, moves, late, delay = {}, [], 0, 0
    for vehicle_id, visits in result["routes"].items():
        routes[vehicle_id] = []
        for order, (stop, arrival) in enumerate(visits, start=1):
            routes[vehicle_id].append({"delivery_id": stop.delivery_id, "eta": min_to_hhmm(arrival),
                                       "eta_min": round(arrival), "stop_order": order, "from": stop.owner,
                                       "deadline_min": stop.deadline_min, "customer": stop.customer,
                                       "phone": stop.phone, "planned_min": stop.planned_min})
            late += arrival > stop.deadline_min
            if stop.affected:
                delay += max(0, round(arrival) - stop.planned_min)
            if stop.owner != vehicle_id:
                moves.append({"delivery_id": stop.delivery_id, "from": stop.owner, "to": vehicle_id,
                              "text": f"{stop.delivery_id} → {names[vehicle_id]} ({vehicle_id})"})
    km_opt = sum(route_eval(problem, by_vehicle[vid], [s for s, _ in visits])[1]
                 for vid, visits in result["routes"].items())
    comparison = _comparison(problem, rule_plan, {"misses": late + len(result["dropped"]), "delay": delay,
                                                  "km": round(km_opt, 1)})
    return {"available": True, "status": result["status"], "seconds": result["seconds"], "thorough": thorough,
            "routes": routes, "moves": moves, "dropped": [s.delivery_id for s in result["dropped"]],
            "detours": {road: {"km": km, "min": minutes, "via": problem.via.get(road)}
                        for road, (km, minutes) in problem.detours.items()},
            "vehicles": sorted(routes), "comparison": comparison,
            "messages": _messages(problem, routes, rule_plan)}


def _comparison(problem, rule_plan, optimised):
    """No action / rule plan / optimised – on the same vehicles and the same clock."""
    ba = rule_plan.get("before_after") or {}
    by_vehicle = {v.vehicle_id: v for v in problem.vehicles}
    original = {v.vehicle_id: sorted((s for s in problem.stops if s.owner == v.vehicle_id), key=lambda s: s.planned_min)
                for v in problem.vehicles}
    km_before = sum(route_eval(problem, by_vehicle[vid], stops, detour=False)[1] for vid, stops in original.items())
    after = {r["delivery_id"]: r for r in rule_plan.get("after") or []}
    rerouted = {a["target"].replace("vehicle ", "") for a in rule_plan.get("actions") or []
                if a.get("action_type") == "reroute"}
    stops_by_id = {s.delivery_id: s for s in problem.stops}
    rule_routes = {vid: [] for vid in by_vehicle}
    for stop in problem.stops:
        row = after.get(stop.delivery_id)
        vid = row["vehicle_id"] if row else stop.owner
        eta = row["new_eta"] if row else min_to_hhmm(stop.planned_min)
        if vid in rule_routes:
            rule_routes[vid].append((eta, stops_by_id[stop.delivery_id]))
    km_rules = sum(route_eval(problem, by_vehicle[vid], [s for _, s in sorted(items, key=lambda t: t[0])],
                              detour=vid in rerouted)[1] for vid, items in rule_routes.items())
    return {"before": {"misses": ba.get("misses_before", 0), "delay": ba.get("delay_before", 0),
                       "km": round(km_before, 1)},
            "rules": {"misses": ba.get("misses_after", 0), "delay": ba.get("delay_after", 0), "km": round(km_rules, 1)},
            "optimised": optimised}


def _messages(problem, routes, rule_plan):
    """Driver messages (new stop order, parcels to collect) and customer SMS for ETAs that moved later."""
    cause = (rule_plan.get("disruption") or {}).get("road_name") or "the disruption"
    names = {v.vehicle_id: v.driver for v in problem.vehicles}
    beyond_block = {s.delivery_id for s in problem.stops if s.needs}
    out = []
    for vehicle_id, stops in routes.items():
        original = [s.delivery_id for s in sorted((s for s in problem.stops if s.owner == vehicle_id),
                                                  key=lambda s: s.planned_min)]
        new = [s["delivery_id"] for s in stops]
        if new == original and not set(new) & beyond_block:  # same stops, same order, no detour: nothing to say
            continue
        driver = names.get(vehicle_id, vehicle_id)
        collect = [f"{s['delivery_id']} from {names.get(s['from'], s['from'])}" for s in stops
                   if s["from"] != vehicle_id]
        order = ", ".join(f"{s['delivery_id']} {s['eta']}" for s in stops) or "no stops"
        text = (f"{driver}, new route (avoid {cause}): {order}."
                + (f" Collect {', '.join(collect)}." if collect else ""))
        out.append({"kind": "driver", "vehicle_id": vehicle_id, "to": f"{driver} ({vehicle_id})", "text": text})
    for stops in routes.values():
        for s in stops:
            if s["eta_min"] - s["planned_min"] >= 15:
                out.append({"kind": "customer", "customer": s["customer"], "phone": s["phone"],
                            "to": f"{s['customer']} ({s['phone']})",
                            "text": f"Hi {s['customer']}, your delivery {s['delivery_id']} is delayed due to "
                                    f"{'a problem on ' + cause if cause != 'the disruption' else cause}. "
                                    f"New ETA: {s['eta']}. Sorry for the trouble. – DEPORT Logistics"})
    return out
