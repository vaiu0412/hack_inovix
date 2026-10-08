"""WHAT CHANGED? Turn a free-text disruption report into a structured dict.

Rule-based parsing always works. If GEMINI_API_KEY or GROQ_API_KEY is set,
we try an LLM first and fall back to rules on any error.
Supports simple Tanglish ("accident aachu", "mazhai", "late aagum", ...).
"""
import json
import os
import re
import urllib.request

SEVERITIES = ["low", "medium", "high", "critical"]

# Checked in this order: the first type with a matching keyword wins.
TYPE_KEYWORDS = [
    ("breakdown", ["breakdown", "break down", "broke down", "puncture", "flat tyre", "flat tire",
                   "engine", "vandi nikkudhu", "vandi ninnuduchu", "repair"]),
    ("accident", ["accident", "crash", "collision", "collided", "mothiduchu"]),
    ("flood", ["flood", "flooding", "waterlogging", "water logging", "rain", "mazhai", "thanni"]),
    ("protest", ["protest", "strike", "rally", "procession", "bandh", "dharna", "maraiyal"]),
    ("closure", ["closed", "closure", "road work", "roadwork", "maintenance", "diversion",
                 "barricade", "blocked", "block"]),
    ("traffic", ["traffic", "jam", "congestion", "slow moving", "nerisal"]),
    ("requirement_change", ["deadline", "earlier", "prepone", "postpone", "reschedule",
                            "wants delivery", "requirement", "change order", "cancel"]),
]

BASE_SEVERITY = {
    "accident": "high", "closure": "high", "breakdown": "high", "flood": "medium",
    "protest": "medium", "traffic": "medium", "requirement_change": "low", "unknown": "medium",
}

DEFAULT_DURATION = {
    "accident": 60, "closure": 120, "breakdown": 60, "flood": 90,
    "protest": 90, "traffic": 30, "requirement_change": 0, "unknown": 60,
}

STRONG_WORDS = ["blocked", "completely", "fully", "full ah", "full-ah", "totally", "major",
                "severe", "heavy", "romba", "huge", "massive", "serious"]
WEAK_WORDS = ["minor", "slight", "small", "konjam", "little", "partially", "partial"]

DURATION_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|hr|h|mani(?:\s*neram)?|minutes?|mins?|min|m)\b"
)
REG_RE = re.compile(r"\bTN[\s-]?(\d{2})[\s-]?([A-Z]{1,2})[\s-]?(\d{3,4})\b", re.IGNORECASE)
VEHICLE_ID_RE = re.compile(r"\bV(\d{1,2})\b", re.IGNORECASE)


# ---------------------------------------------------------------- rule helpers
def _contains(text, word):
    return re.search(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])", text) is not None


def detect_type(text):
    for dtype, words in TYPE_KEYWORDS:
        if any(_contains(text, w) for w in words):
            return dtype
    return "unknown"


def detect_duration(text):
    """Return minutes, or None if no duration is mentioned."""
    if re.search(r"half\s*(an)?\s*(hour|hr)|arai\s*mani", text):
        return 30
    match = DURATION_RE.search(text)
    if match:
        value, unit = float(match.group(1)), match.group(2)
        if unit.startswith("m") and not unit.startswith("mani"):
            return int(round(value))
        return int(round(value * 60))
    if re.search(r"\b(an|one|oru)\s*(hour|hr|mani)", text):
        return 60
    return None


def match_road(text, roads):
    """Find the road mentioned in the text using aliases.

    Longest alias wins (more specific), ties go to the earliest mention.
    Returns (road_id, road_name, alias) or (None, None, None).
    """
    best = None
    for _, road in roads.iterrows():
        for alias in road["aliases"] + [road["name"].lower()]:
            m = re.search(r"(?<![a-z0-9])" + re.escape(alias) + r"(?![a-z0-9])", text)
            if m:
                key = (len(alias), -m.start())
                if best is None or key > best[0]:
                    best = (key, road["road_id"], road["name"], alias)
    if best is None:
        return None, None, None
    return best[1], best[2], best[3]


def match_vehicle(text, vehicles):
    """Find a vehicle by reg number, id (V3) or driver name."""
    reg = REG_RE.search(text)
    if reg:
        wanted = re.sub(r"[\s-]", "", reg.group(0)).upper()
        for _, v in vehicles.iterrows():
            if re.sub(r"[\s-]", "", v["reg_no"]).upper() == wanted:
                return v["vehicle_id"]
    vid = VEHICLE_ID_RE.search(text)
    if vid and f"V{int(vid.group(1))}" in set(vehicles["vehicle_id"]):
        return f"V{int(vid.group(1))}"
    for _, v in vehicles.iterrows():
        if _contains(text.lower(), v["driver"].lower()):
            return v["vehicle_id"]
    return None


def detect_severity(text, dtype, duration, duration_given):
    level = SEVERITIES.index(BASE_SEVERITY.get(dtype, "medium"))
    if any(_contains(text, w) for w in STRONG_WORDS):
        level += 1
    if any(_contains(text, w) for w in WEAK_WORDS):
        level -= 1
    if duration_given and duration >= 120:
        level += 1
    if duration_given and duration <= 30:
        level -= 1
    return SEVERITIES[max(0, min(level, 3))]


def parse_rules(text, data):
    raw = text or ""
    low = raw.lower()
    dtype = detect_type(low)
    duration = detect_duration(low)
    duration_given = duration is not None
    if duration is None:
        duration = DEFAULT_DURATION[dtype]
    road_id, road_name, alias = match_road(low, data["roads"])
    vehicle_id = match_vehicle(raw, data["vehicles"])

    confidence = 0.4
    confidence += 0.25 if (road_id or vehicle_id) else 0
    confidence += 0.2 if dtype != "unknown" else 0
    confidence += 0.1 if duration_given else 0
    return {
        "type": dtype,
        "road_id": road_id,
        "road_name": road_name,
        "location_text": alias or "",
        "severity": detect_severity(low, dtype, duration, duration_given),
        "duration_min": int(duration),
        "vehicle_id": vehicle_id,
        "confidence": round(min(confidence, 0.95), 2),
        "method": "rules",
        "raw_text": raw,
    }


# ---------------------------------------------------------------- optional LLM
def llm_available():
    return bool(os.getenv("GEMINI_API_KEY") or os.getenv("GROQ_API_KEY"))


def call_llm(prompt, want_json=False, timeout=10):
    """Send a prompt to Gemini or Groq. Returns text, raises on any problem."""
    if os.getenv("GEMINI_API_KEY"):
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        if want_json:
            body["generationConfig"] = {"responseMimeType": "application/json"}
        headers = {"Content-Type": "application/json", "x-goog-api-key": os.environ["GEMINI_API_KEY"]}
        reply = _post_json(url, body, headers, timeout)
        return reply["candidates"][0]["content"]["parts"][0]["text"]

    if os.getenv("GROQ_API_KEY"):
        url = "https://api.groq.com/openai/v1/chat/completions"
        body = {
            "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        if want_json:
            body["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"}
        reply = _post_json(url, body, headers, timeout)
        return reply["choices"][0]["message"]["content"]

    raise RuntimeError("No LLM API key set")


def _post_json(url, body, headers, timeout):
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def parse_llm(text, data):
    roads = "\n".join(f"- {r.road_id}: {r.name}" for r in data["roads"].itertuples())
    vehicles = "\n".join(f"- {v.vehicle_id}: {v.reg_no} driver {v.driver}" for v in data["vehicles"].itertuples())
    prompt = f"""You extract logistics disruptions in Coimbatore from short messages (English or Tanglish).
Roads:
{roads}
Vehicles:
{vehicles}
Return ONLY JSON with keys: type (one of {[t for t, _ in TYPE_KEYWORDS]} or "unknown"),
road_id (from the list or null), location_text, severity (low/medium/high/critical),
duration_min (integer), vehicle_id (from the list or null), confidence (0-1).
Message: {text}"""
    out = json.loads(call_llm(prompt, want_json=True))

    road_ids = set(data["roads"]["road_id"])
    dtype = out.get("type") if out.get("type") in BASE_SEVERITY else "unknown"
    road_id = out.get("road_id") if out.get("road_id") in road_ids else None
    vehicle_id = out.get("vehicle_id") if out.get("vehicle_id") in set(data["vehicles"]["vehicle_id"]) else None
    severity = out.get("severity") if out.get("severity") in SEVERITIES else BASE_SEVERITY[dtype]
    if road_id is None and vehicle_id is None:
        raise ValueError("LLM found no road or vehicle")
    road_name = data["roads"].set_index("road_id")["name"].get(road_id) if road_id else None
    return {
        "type": dtype,
        "road_id": road_id,
        "road_name": road_name,
        "location_text": str(out.get("location_text") or ""),
        "severity": severity,
        "duration_min": int(float(out.get("duration_min") or DEFAULT_DURATION[dtype])),
        "vehicle_id": vehicle_id,
        "confidence": round(float(out.get("confidence") or 0.8), 2),
        "method": "llm",
        "raw_text": text,
    }


# ---------------------------------------------------------------- public API
def parse_disruption(text, data, use_llm=True):
    """Parse a disruption message. Always returns a dict (rules as fallback)."""
    if use_llm and llm_available():
        try:
            return parse_llm(text, data)
        except Exception:
            pass  # any LLM problem -> rules
    return parse_rules(text, data)


SAMPLE_MESSAGES = [
    "Accident near Avinashi Road, road blocked for 2 hours",
    "Heavy rain flooding at Trichy Road, expect 45 mins delay",
    "Van TN-37-AB-1234 puncture near Gandhipuram 100 feet road",
    "Protest at Town Hall, traffic slow for 1.5 hr",
    "Traffic jam on Sathy Road around 30 mins",
    "Avinashi road la accident aachu, full ah block, 2 mani neram aagum",
    "Mettupalayam road la mazhai romba, late aagum",
    "Pollachi road closed for maintenance for 3 hrs",
    "Customer at RS Puram wants delivery earlier, deadline changed",
    "Murugan vandi breakdown aachu near Race Course",
]


if __name__ == "__main__":
    from modules.data_loader import load_all

    data = load_all()
    for msg in SAMPLE_MESSAGES + ["Something happened somewhere"]:
        p = parse_disruption(msg, data, use_llm=False)
        print(f"{msg[:55]:57} -> {p['type']:<18} {str(p['road_id']):<5} {p['severity']:<8} "
              f"{p['duration_min']:>4}m veh={p['vehicle_id']} conf={p['confidence']}")
