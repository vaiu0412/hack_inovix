"""WHAT CHANGED? Turn a free-text disruption report into a structured dict.

Rule-based parsing always works. If GEMINI_API_KEY or GROQ_API_KEY is set,
we try an LLM first and fall back to rules on any error.
Supports simple Tanglish ("accident aachu", "mazhai", "rendu mani neram") and common
Tamil words, and finds places even when they are misspelled (see modules/places.py).
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

from modules.places import best_road

SEVERITIES = ["low", "medium", "high", "critical"]

# Checked in this order: the first type with a matching keyword wins.
TYPE_KEYWORDS = [
    ("breakdown", ["breakdown", "break down", "broke down", "brake down", "puncture", "flat tyre",
                   "flat tire", "tyre burst", "tire burst", "engine", "vandi nikkudhu", "vandi ninnuduchu",
                   "repair", "பஞ்சர்", "பழுது", "ரிப்பேர்"]),
    ("accident", ["accident", "crash", "collision", "collided", "mothiduchu", "விபத்து", "மோதல்"]),
    ("flood", ["flood", "flooding", "waterlogging", "water logging", "rain", "mazhai", "thanni",
               "மழை", "வெள்ளம்"]),
    ("protest", ["protest", "strike", "rally", "procession", "bandh", "dharna", "maraiyal",
                 "போராட்டம்", "மறியல்"]),
    ("closure", ["closed", "closure", "road work", "roadwork", "maintenance", "diversion",
                 "barricade", "blocked", "block", "அடைப்பு", "பிளாக்"]),
    ("traffic", ["traffic", "jam", "congestion", "slow moving", "nerisal", "டிராபிக்", "நெரிசல்"]),
    ("customer_unavailable", ["customer not available", "not available", "door locked", "no answer",
                              "not picking", "not answering", "customer illa", "aal illa", "phone edukala"]),
    ("requirement_change", ["deadline", "earlier", "prepone", "postpone", "reschedule",
                            "wants delivery", "requirement", "change order", "cancel"]),
]

BASE_SEVERITY = {
    "accident": "high", "closure": "high", "breakdown": "high", "flood": "medium",
    "protest": "medium", "traffic": "medium", "requirement_change": "low", "customer_unavailable": "low",
    "unknown": "medium",
}

DEFAULT_DURATION = {
    "accident": 60, "closure": 120, "breakdown": 60, "flood": 90,
    "protest": 90, "traffic": 30, "requirement_change": 0, "customer_unavailable": 0, "unknown": 60,
}

STRONG_WORDS = ["blocked", "completely", "fully", "full ah", "full-ah", "totally", "major",
                "severe", "heavy", "romba", "huge", "massive", "serious"]
WEAK_WORDS = ["minor", "slight", "small", "konjam", "little", "partially", "partial"]

DURATION_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|hr|h|mani(?:\s*neram)?|minutes?|mins?|min|m)\b"
)
TAMIL_DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(மணி|நிமிட)")
# spoken numbers in voice notes: "two hours", "rendu mani", "muppathu minutes"
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "fifteen": 15, "twenty": 20,
    "thirty": 30, "forty": 40, "forty five": 45, "fifty": 50, "oru": 1, "rendu": 2, "randu": 2,
    "moonu": 3, "munu": 3, "naalu": 4, "nalu": 4, "anju": 5, "pathu": 10, "irupathu": 20, "muppathu": 30,
}
NUMBER_WORD_RE = re.compile(
    r"\b(" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")\s+(?=(hours?|hrs?|hr|mani|minutes?|mins?|min))"
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
    if re.search(r"half\s*(an)?\s*(hour|hr)|arai\s*mani|அரை\s*மணி", text):
        return 30
    text = NUMBER_WORD_RE.sub(lambda m: f"{NUMBER_WORDS[m.group(1)]} ", text)
    tamil = TAMIL_DURATION_RE.search(text)
    if tamil:
        value = float(tamil.group(1))
        return int(round(value * 60 if tamil.group(2) == "மணி" else value))
    match = DURATION_RE.search(text)
    if match:
        value, unit = float(match.group(1)), match.group(2)
        if unit.startswith("m") and not unit.startswith("mani"):
            return int(round(value))
        return int(round(value * 60))
    if re.search(r"\b(an|one|oru)\s*(hour|hr|mani)", text):
        return 60
    return None


def locate(text):
    """Fuzzy place lookup: {road_id, road_name, place, alias, score, suggestions}."""
    best, others = best_road(text)
    suggestions = [f"{m['place']} ({m['road_name']})" if m["place"] != m["road_name"] else m["road_name"]
                   for m in others]
    if best is None:
        return {"road_id": None, "road_name": None, "place": None, "alias": "", "score": 0,
                "suggestions": suggestions}
    return {**{k: best[k] for k in ["road_id", "road_name", "place", "alias", "score"]}, "suggestions": suggestions}


def match_road(text, roads=None):
    """Find the road mentioned in the text. Returns (road_id, road_name, alias) or (None, None, None)."""
    found = locate(text)
    return found["road_id"], found["road_name"], found["alias"] or None


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
    where = locate(raw)
    road_id = where["road_id"]
    vehicle_id = match_vehicle(raw, data["vehicles"])

    confidence = 0.4
    confidence += 0.25 * where["score"] / 100 if road_id else (0.25 if vehicle_id else 0)
    confidence += 0.2 if dtype != "unknown" else 0
    confidence += 0.1 if duration_given else 0
    return {
        "type": dtype,
        "road_id": road_id,
        "road_name": where["road_name"],
        "place": where["place"],
        "suggestions": where["suggestions"],
        "location_text": where["alias"] or "",
        "severity": detect_severity(low, dtype, duration, duration_given),
        "duration_min": int(duration),
        "vehicle_id": vehicle_id,
        "confidence": round(min(confidence, 0.95), 2),
        "method": "rules",
        "raw_text": raw,
    }


# ---------------------------------------------------------------- optional LLM
LLM_COOLDOWN_SEC = 300  # after a failure, skip the LLM for 5 minutes
# Groq chat models open to normal (free/developer) keys, best first. Override with GROQ_MODEL.
GROQ_MODELS = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "llama-3.1-8b-instant"]
# Groq's firewall (Cloudflare) blocks Python's default "Python-urllib" identity with
# HTTP 403 "error code: 1010", so every AI request names the app instead.
USER_AGENT = "Ripple/2.0 (+https://github.com/vaiu0412/hack_inovix)"
# last outcome of an AI call, shown on the Activity page (never contains the key)
LLM_STATUS = {"provider": None, "model": None, "ok_at": None, "error": None, "error_at": None}
_llm_paused_until = 0.0


def setting(name, default=None):
    """Read a key from environment variables, or from Streamlit secrets when deployed.

    Placeholders copied from secrets.toml.example ("paste-your-...") count as not set.
    """
    value = os.getenv(name)
    if not value:
        try:
            import streamlit as st
            value = st.secrets.get(name)
        except Exception:  # no secrets file
            value = None
    if not value or str(value).startswith("paste-your"):
        return default
    return value


def offline():
    """RIPPLE_OFFLINE=1 switches every AI/network call off (used by the tests)."""
    return os.getenv("RIPPLE_OFFLINE") == "1"


def llm_available():
    return not offline() and bool(setting("GEMINI_API_KEY") or setting("GROQ_API_KEY"))


def llm_status():
    """What happened on the last AI call, for the status line in the app."""
    paused = max(0, int(_llm_paused_until - time.time()))
    return {**LLM_STATUS, "available": llm_available(), "paused_sec": paused}


def call_llm(prompt, want_json=False, timeout=15):
    """Send a prompt to Gemini or Groq. Returns text, raises on any problem.

    One failure (bad key, no network, timeout) pauses the LLM for a while,
    so the app falls back to rules instantly instead of waiting every time.
    """
    global _llm_paused_until
    if time.time() < _llm_paused_until:
        raise RuntimeError("LLM paused after a recent failure")
    try:
        text = _call_provider(prompt, want_json, timeout)
    except Exception as error:
        _llm_paused_until = time.time() + LLM_COOLDOWN_SEC
        LLM_STATUS.update(error=str(error)[:300], error_at=time.strftime("%H:%M:%S"))
        print(f"[ripple] AI call failed, using rules for {LLM_COOLDOWN_SEC // 60} min: {error}", file=sys.stderr)
        raise
    LLM_STATUS.update(ok_at=time.strftime("%H:%M:%S"), error=None)
    return text


def json_from_text(text):
    """Parse a JSON object from a model reply, even if it is wrapped in prose or ``` fences."""
    try:
        return json.loads(text)
    except (TypeError, ValueError):
        start, end = str(text).find("{"), str(text).rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(text[start:end + 1])


def _http_error_text(error):
    """Groq/Gemini error message without anything sensitive."""
    try:
        raw = error.read().decode(errors="replace")
    except Exception:
        raw = ""
    try:
        detail = json.loads(raw).get("error", {})
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
    except Exception:
        message = f"{error.reason} ({raw.strip()[:80]})" if raw.strip() else error.reason
    return f"HTTP {error.code}: {message}"


def _call_provider(prompt, want_json, timeout):
    if setting("GEMINI_API_KEY"):
        model = setting("GEMINI_MODEL", "gemini-2.5-flash")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {"contents": [{"parts": [{"text": prompt}]}]}
        if want_json:
            body["generationConfig"] = {"responseMimeType": "application/json"}
        headers = {"Content-Type": "application/json", "x-goog-api-key": setting("GEMINI_API_KEY")}
        reply = _post_json(url, body, headers, timeout)
        LLM_STATUS.update(provider="Gemini", model=model)
        return reply["candidates"][0]["content"]["parts"][0]["text"]

    if setting("GROQ_API_KEY"):
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {setting('GROQ_API_KEY')}"}
        errors = []
        # Groq retires or restricts models over time, so try the next one if a model is refused.
        # If a model refuses JSON mode, ask again in plain text (json_from_text reads the reply).
        for model in dict.fromkeys([setting("GROQ_MODEL"), *GROQ_MODELS]):
            if not model:
                continue
            for json_mode in ([True, False] if want_json else [False]):
                body = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}
                if model.startswith("openai/gpt-oss"):
                    body["reasoning_effort"] = "low"  # quick answers for short extraction tasks
                if json_mode:
                    body["response_format"] = {"type": "json_object"}
                try:
                    reply = _post_json(url, body, headers, timeout)
                except urllib.error.HTTPError as error:
                    errors.append(f"{model}: {_http_error_text(error)}")
                    if error.code == 401:
                        raise RuntimeError("Groq rejected the API key (HTTP 401)") from None
                    if error.code in (403, 404):
                        break  # this model is not available for the key -> next model
                    if error.code in (400, 422):
                        continue  # maybe JSON mode was refused -> try plain text, then the next model
                    raise RuntimeError(errors[-1]) from None
                LLM_STATUS.update(provider="Groq", model=model)
                return reply["choices"][0]["message"]["content"]
        raise RuntimeError("No Groq model accepted the request – " + " | ".join(errors[-3:]))

    raise RuntimeError("No LLM API key set")


def _post_json(url, body, headers, timeout):
    headers = {"User-Agent": USER_AGENT, **headers}
    request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


def parse_llm(text, data):
    from modules.data_loader import load_places

    roads = "\n".join(f"- {r.road_id}: {r.name}" for r in data["roads"].itertuples())
    areas = ", ".join(f"{p.name}={p.road_id}" for p in load_places().itertuples() if p.kind != "road")
    vehicles = "\n".join(f"- {v.vehicle_id}: {v.reg_no} driver {v.driver}" for v in data["vehicles"].itertuples())
    prompt = f"""You extract logistics disruptions in Coimbatore from short messages (English or Tanglish).
Roads:
{roads}
Areas and landmarks (name=road_id): {areas}
Vehicles:
{vehicles}
Return ONLY JSON with keys: type (one of {[t for t, _ in TYPE_KEYWORDS]} or "unknown"),
road_id (from the list or null), location_text, severity (low/medium/high/critical),
duration_min (integer), vehicle_id (from the list or null), confidence (0-1).
Message: {text}"""
    out = json_from_text(call_llm(prompt, want_json=True))

    road_ids = set(data["roads"]["road_id"])
    dtype = out.get("type") if out.get("type") in BASE_SEVERITY else "unknown"
    road_id = out.get("road_id") if out.get("road_id") in road_ids else None
    place = None
    if road_id is None:  # the model may answer with a place name instead of an id
        where = locate(f"{out.get('location_text') or ''} {text}")
        road_id, place = where["road_id"], where["place"]
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
        "place": place or (str(out.get("location_text")) if out.get("location_text") else road_name),
        "suggestions": [],
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
