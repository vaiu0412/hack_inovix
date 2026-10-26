# Real-world data: GPS, weather, traffic

Three live feeds, each optional, each with a Demo mode, all ending in the **same flow** as a partner's report:
impact → recommended plan → the Branch Admin approves.

| Feed | With a key | Without (Demo mode) | Goes into |
|---|---|---|---|
| **GPS** | partner phones share their position every 30 s while on duty | **Simulate movement** (Command Center → Live feeds): vehicles drive toward their next stop | vehicle positions, map trails, "GPS 12 s ago" in the partner panel |
| **Weather** | OpenWeatherMap every 10 min (`OWM_API_KEY`) | set by hand (Clear / Light rain / Heavy rain) | the delay model's rain feature; heavy rain opens a **Weather risk** alert |
| **Traffic** | TomTom Traffic Flow every 10 min (`TOMTOM_API_KEY`) | **Check traffic (demo)** plays a scripted jam on Trichy Road | a **suggestion** the admin confirms (→ alert with a plan) or dismisses |

## GPS (`modules/tracking.py`, `components/geolocation/`)
- The partner app has a tiny location component (plain HTML/JS, no package): the browser asks once, then the phone
  sends its position every 30 s – **only while the partner is on duty** (on break: nothing is shared). The sidebar
  says so: *Sharing location every 30 s (on duty)*, *Location blocked – allow it in the browser* or *Location off*.
- A position updates the partner's own vehicle and the `location_log`. Positions outside Coimbatore are not used,
  so a phone far away never moves a van off the map.
- The Live Map draws each vehicle where it is and its trail of the last 30 minutes; the partner panel shows
  *GPS 12 s ago · ±8 m* or *Simulated 2 min ago*.
- **Simulate movement** (off by default, so the demo numbers stay the same): every on-duty vehicle drives toward its
  next open stop at 22 km/h – except partners whose phone sent real GPS in the last 2 minutes.
- Native app: `POST /me/location {lat, lng, accuracy_m}` with the partner's token.

## Weather (`services/weather.py`, `modules/realtime.py`)
OpenWeatherMap current weather for the branch's city, every 10 minutes: rain in the last hour (mm) and the condition
code → **Clear**, **Light rain** (≥ 0.5 mm/h or a rain code) or **Heavy rain** (≥ 7 mm/h, heavy-rain or
thunderstorm codes). It replaces the hand switch on Command Center and feeds the delay model.
**Heavy rain** opens a **Weather risk** alert in every active branch – flooding on the branch's most flood-prone road
(Avinashi Rd, then Ukkadam–Town Hall, Trichy Rd, 100 Feet Rd – whichever its vehicles use), at most once a day and
never while one is still open. It is a normal alert: who is hit, a plan, Accept / Modify / Reject.

## Traffic (`services/traffic.py`, `modules/realtime.py`)
TomTom Traffic Flow for the middle of each road the branch's vehicles use, every 10 minutes: current vs free-flow
speed → **heavy** (< 45 %), **severe** (< 25 %) or **closed**. Each jam becomes one amber **suggestion** a day on
Command Center and Alerts – *Heavy traffic on Trichy Road · 9 km/h · usually 34* – with **Create alert** (an alert
with a plan: traffic, severity from the jam, about 45 min) or **Dismiss**. Nothing changes until the admin confirms.

## Who runs the feeds
Admin pages every 20 s (the same timer as order escalation) and the API every minute when no page is open
(`FEEDS_SCHEDULER=off` disables it). Each feed keeps its own pace (weather and traffic 10 min). Without keys nothing
is fetched from the network.

## Limits
- TomTom's free tier allows 2,500 requests a day: 10 roads every 10 minutes is about 1,440.
- The flood-prone road list is a simple ranking in `modules/realtime.py` (`FLOOD_PRONE`); adjust it for your city.
- Browsers share location only on https or localhost, after the partner allows it; iPhones stop sharing when the
  page is in the background (a native app – the next phase – keeps sharing).
