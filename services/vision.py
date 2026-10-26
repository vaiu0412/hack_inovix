"""Understand an issue photo with a vision model – optional. Gemini (GEMINI_API_KEY) first, else a Groq vision model
(GROQ_API_KEY, GROQ_VISION_MODEL). Without a key the partner picks the type by hand (the tiles)."""
import base64
import json

import httpx

from modules.parser import TYPE_KEYWORDS, json_from_text, offline, setting

TYPES = [t for t, _ in TYPE_KEYWORDS] + ["unknown"]
SEVERITIES = ("low", "medium", "high", "critical")
GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"
PROMPT = ("A delivery driver in Coimbatore, India took this photo of a problem on their route. "
          f"Return ONLY JSON: {{\"type\": one of {TYPES}, \"severity\": one of {list(SEVERITIES)}, "
          "\"description\": what the photo shows in at most 12 words}. Driver's note: ")


def available():
    """True when a vision-capable key is set (and the app is not offline)."""
    return not offline() and bool(setting("GEMINI_API_KEY") or setting("GROQ_API_KEY"))


def _mime(image):
    return "image/png" if image[:4] == b"\x89PNG" else "image/webp" if image[8:12] == b"WEBP" else "image/jpeg"


def analyse(image, note=""):
    """{type, severity, description, engine} from the photo, or None (no key, unreadable answer, network)."""
    if not available() or not image:
        return None
    data, mime = base64.b64encode(image).decode(), _mime(image)
    prompt = PROMPT + (note or "none")
    try:
        if setting("GEMINI_API_KEY"):
            model = setting("GEMINI_MODEL", "gemini-2.5-flash")
            reply = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": setting("GEMINI_API_KEY")}, timeout=25,
                json={"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": mime, "data": data}}]}],
                      "generationConfig": {"responseMimeType": "application/json"}})
            reply.raise_for_status()
            text, engine = reply.json()["candidates"][0]["content"]["parts"][0]["text"], f"Gemini {model}"
        else:
            model = setting("GROQ_VISION_MODEL", GROQ_VISION_MODEL)
            content = [{"type": "text", "text": prompt},
                       {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}]
            reply = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions", timeout=25,
                headers={"Authorization": f"Bearer {setting('GROQ_API_KEY')}"},
                json={"model": model, "response_format": {"type": "json_object"},
                      "messages": [{"role": "user", "content": content}]})
            reply.raise_for_status()
            text, engine = reply.json()["choices"][0]["message"]["content"], f"Groq {model}"
        found = json_from_text(text) if isinstance(text, str) else text
    except (httpx.HTTPError, KeyError, IndexError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(found, dict) or found.get("type") not in TYPES:
        return None
    severity = found.get("severity") if found.get("severity") in SEVERITIES else "medium"
    return {"type": found["type"], "severity": severity, "description": str(found.get("description", ""))[:120],
            "engine": engine}
