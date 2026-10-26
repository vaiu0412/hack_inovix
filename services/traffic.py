"""Live traffic from TomTom Traffic Flow – optional (TOMTOM_API_KEY). Heavy congestion on a route's road becomes a
suggestion the Branch Admin confirms. Without a key, Demo mode plays a scripted event (Trichy Road jammed) when an
admin runs a traffic check."""
import httpx

from modules.parser import offline, setting

URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"
DEMO_EVENT = {"R2": (9, 34)}  # road -> (km/h now, km/h usually): Trichy Road jammed


def configured():
    """True when a TomTom key is set (and the app is not offline)."""
    return bool(setting("TOMTOM_API_KEY")) and not offline()


def flow(lat, lng):
    """{current_kmph, free_kmph, confidence, closure, source} for the road segment nearest a point, or None."""
    if not configured():
        return None
    try:
        reply = httpx.get(URL, params={"point": f"{lat},{lng}", "unit": "KMPH", "key": setting("TOMTOM_API_KEY")},
                          timeout=8)
        reply.raise_for_status()
        segment = reply.json()["flowSegmentData"]
    except (httpx.HTTPError, ValueError, KeyError):
        return None
    return {"current_kmph": float(segment["currentSpeed"]), "free_kmph": float(segment["freeFlowSpeed"]),
            "confidence": float(segment.get("confidence", 1.0)), "closure": bool(segment.get("roadClosure")),
            "source": "TomTom"}


def demo_flow(road_id):
    """The scripted Demo-mode reading for a road."""
    current, free = DEMO_EVENT.get(road_id, (28, 34))
    return {"current_kmph": float(current), "free_kmph": float(free), "confidence": 1.0, "closure": False,
            "source": "Demo"}


def level(reading):
    """closed, severe, heavy or normal – from closure and current / free-flow speed."""
    if reading.get("closure"):
        return "closed"
    ratio = reading["current_kmph"] / max(reading["free_kmph"], 1.0)
    return "severe" if ratio < 0.25 else "heavy" if ratio < 0.45 else "normal"
