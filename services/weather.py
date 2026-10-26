"""Live weather from OpenWeatherMap – optional (OWM_API_KEY). Without a key the weather is set by hand on Command
Center (Demo mode). The reading feeds the delay model (rain) and, for heavy rain, a "Weather risk" alert."""
import httpx

from modules.parser import offline, setting

URL = "https://api.openweathermap.org/data/2.5/weather"
HEAVY_CODES = {502, 503, 504, 522, 531}  # heavy / extreme / shower rain


def configured():
    """True when an OpenWeatherMap key is set (and the app is not offline)."""
    return bool(setting("OWM_API_KEY")) and not offline()


def classify(rain_mm, code=800):
    """clear, light_rain or heavy_rain from mm of rain in the last hour and the OWM condition code."""
    rain_mm = float(rain_mm or 0)
    if 200 <= code < 300 or code in HEAVY_CODES or rain_mm >= 7:
        return "heavy_rain"
    if rain_mm >= 0.5 or 300 <= code < 600:
        return "light_rain"
    return "clear"


def current(lat, lng):
    """{weather, rain_mm, description, temp_c, source} for a point, or None (no key, network error)."""
    if not configured():
        return None
    try:
        reply = httpx.get(URL, params={"lat": lat, "lon": lng, "appid": setting("OWM_API_KEY"), "units": "metric"},
                          timeout=8)
        reply.raise_for_status()
        data = reply.json()
    except (httpx.HTTPError, ValueError):
        return None
    rain = float((data.get("rain") or {}).get("1h", 0.0))
    condition = (data.get("weather") or [{}])[0]
    return {"weather": classify(rain, int(condition.get("id", 800))), "rain_mm": round(rain, 1),
            "description": condition.get("description", ""), "temp_c": (data.get("main") or {}).get("temp"),
            "source": "OpenWeatherMap"}
