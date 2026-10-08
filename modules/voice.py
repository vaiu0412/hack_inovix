"""Voice note -> text. Tries the best engine that is available and never crashes.

1. Groq Whisper   (GROQ_API_KEY)   – best for Tamil / Tanglish, free tier
2. Gemini audio   (GEMINI_API_KEY)
3. SpeechRecognition (free Google web speech, no key, needs internet) – en-IN, then ta-IN
4. None -> the app asks the partner to type one line (the audio is still kept)
"""
import base64
import io
import json
import urllib.request
import uuid

from modules.parser import offline, setting

# Helps Whisper spell local names correctly.
WHISPER_HINT = ("Delivery driver in Coimbatore reporting a problem, Tamil and English mixed. "
                "Places: Avinashi Road, Trichy Road, Gandhipuram, RS Puram, Peelamedu, Hope College, "
                "PSG Tech, KMCH, Ukkadam, Town Hall, Singanallur, Saravanampatti, Race Course.")
TIMEOUT_SEC = 20


def transcribe(audio_bytes, filename="voice-note.wav", mime="audio/wav"):
    """Return {"text", "engine"} or None when no engine could understand the audio."""
    if not audio_bytes or offline():
        return None
    engines = [("Groq Whisper", _groq), ("Gemini", _gemini), ("Google speech (free)", _speech_recognition)]
    for name, engine in engines:
        try:
            text = engine(audio_bytes, filename, mime)
        except Exception:
            continue  # try the next engine
        if text and text.strip():
            return {"text": text.strip(), "engine": name}
    return None


def available_engines():
    names = []
    if setting("GROQ_API_KEY"):
        names.append("Groq Whisper")
    if setting("GEMINI_API_KEY"):
        names.append("Gemini")
    try:
        import speech_recognition  # noqa: F401
        names.append("Google speech (free)")
    except ImportError:
        pass
    return names


# ---------------------------------------------------------------- engines
def _groq(audio_bytes, filename, mime):
    key = setting("GROQ_API_KEY")
    if not key:
        return None
    fields = {"model": setting("GROQ_WHISPER_MODEL", "whisper-large-v3"), "response_format": "json",
              "temperature": "0", "prompt": WHISPER_HINT}
    body, content_type = _multipart(fields, "file", filename, mime, audio_bytes)
    request = urllib.request.Request("https://api.groq.com/openai/v1/audio/transcriptions", data=body,
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": content_type},
                                     method="POST")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:
        return json.loads(response.read().decode())["text"]


def _gemini(audio_bytes, filename, mime):
    key = setting("GEMINI_API_KEY")
    if not key:
        return None
    model = setting("GEMINI_MODEL", "gemini-2.5-flash")
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(audio_bytes).decode()}},
        {"text": "Transcribe this voice note exactly. It may mix Tamil and English. Write Tamil words "
                 "in English letters (Tanglish). Output only the transcript."},
    ]}]}
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(body).encode(), headers={"Content-Type": "application/json", "x-goog-api-key": key},
        method="POST")
    with urllib.request.urlopen(request, timeout=TIMEOUT_SEC) as response:
        reply = json.loads(response.read().decode())
    return reply["candidates"][0]["content"]["parts"][0]["text"]


def _speech_recognition(audio_bytes, filename, mime):
    import speech_recognition as sr

    recognizer = sr.Recognizer()
    recognizer.operation_timeout = TIMEOUT_SEC
    with sr.AudioFile(io.BytesIO(audio_bytes)) as source:
        audio = recognizer.record(source)
    for language in ("en-IN", "ta-IN"):
        try:
            return recognizer.recognize_google(audio, language=language)
        except sr.UnknownValueError:
            continue
    return None


def _multipart(fields, file_field, filename, mime, data):
    boundary = uuid.uuid4().hex
    lines = []
    for name, value in fields.items():
        lines += [f"--{boundary}", f'Content-Disposition: form-data; name="{name}"', "", str(value)]
    head = "\r\n".join(lines + [f"--{boundary}",
                                f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"',
                                f"Content-Type: {mime}", "", ""]).encode()
    tail = f"\r\n--{boundary}--\r\n".encode()
    return head + data + tail, f"multipart/form-data; boundary={boundary}"


if __name__ == "__main__":
    import sys

    print("Engines available:", available_engines() or "none (partners type instead)")
    if len(sys.argv) > 1:
        with open(sys.argv[1], "rb") as f:
            print(transcribe(f.read()))
    print("voice OK")
