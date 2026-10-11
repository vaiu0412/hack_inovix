# Optimised plan (OR-Tools)

Every alert with a ripple gets two plans: the **rule-based plan** (backup van, reroute, prioritise, notify – easy to
explain) and an **optimised plan** from Google OR-Tools. Alerts → step 3 shows them side by side; the rule plan is
selected by default and the admin chooses which one **Accept** applies.

| Demo: 2-hour accident on Avinashi Road | No action | Rule plan | Optimised |
|---|---|---|---|
| Missed deadlines | 3 | 0 | 0 |
| Total delay (hit stops) | 855 min | 154 min | 129 min |
| Total km (vehicles in scope) | 59 | 95.5 | 52.4 |

The optimised plan reroutes and re-orders the stops without moving parcels between vans; the rule plan sends the
urgent ones to the backup van, which costs driving. Both are valid – the numbers make the trade-off visible.

## The model (`modules/optimizer.py`)
A vehicle routing problem with time windows and capacities, for **the affected branch only**:

- **Vehicles:** the ones hit by the disruption, the branch's backup vehicles, and nearby partners (within 6 km)
  with spare capacity. Broken-down vehicles and partners on break are left out.
- **Stops:** every open stop of the hit vehicles (may move to any vehicle in scope) and the nearby partners' own
  stops (stay with them). A parcel only goes on a vehicle it fits (bike = small, car ≤ medium, van/truck any).
- **Capacity:** open stops per vehicle (bike 8, car 10, van 12, truck 14).
- **Time:** every vehicle starts now from where it is. Driving minutes come from the cached OSRM leg when there is
  one, else the straight line × 1.3 at 25 km/h (the same model as the rule plan), plus 5 min at each stop. No stop
  is served before its planned ETA, so untouched routes keep their times.
- **The block:** a stop beyond a blocked road costs the detour (via the best alternate road) once.
- **Moving a parcel:** costs the trip to meet its current driver plus a 5-minute handover (once per pickup) and
  10 minutes of "is it worth it" in the objective.
- **Deadlines:** soft – every minute late costs by priority (medical 20, perishable 12, express 6, standard 3
  minutes of driving per minute late).
- **Leaving a stop out:** only when nothing else fits, at a very high cost by priority – so **medical is served
  first**. Left-out stops go back to the Assign Work queue.
- **Search:** cheapest-arc start + local search (milliseconds for a branch). **Improve (5 s)** adds guided local
  search for the full 5-second limit.

## Applying it
Accept → *optimised* writes, in one transaction: every stop's vehicle, ETA and order; vehicles avoid the blocked
road (their route uses the detour road); each partner whose stops changed gets "new route: D08 09:30, D07 09:36 …"
(+ "collect D06 from Murugan" for moved parcels); customers whose ETA moved 15+ minutes later get an SMS; the block
is recorded and the alert closes. The success card then shows the optimised plan's Before → After.

## Without OR-Tools
`ortools` is in `requirements.txt`. If it is missing (or the solver fails), the alert says so and the rule-based plan
works exactly as before.

## Tests (`tests/test_optimizer.py`)
Capacity is never exceeded · medical is served first when not everything fits · medical is on time when not
everyone can be · parcels fit their vehicle and pinned stops stay · the time limit holds (60 stops, guided search,
1 s) · the alert offers both plans with the same rule numbers · accepting the optimised plan applies its routes ·
Improve stays within the limit and the branch · without OR-Tools the rule plan stays.
