"""Find the road a message talks about, even with typos, missing spaces, short forms or Tamil.

"avinasi rd", "avinashiroad", "Avanashi", "R.S.Puram", "100ft road", "pelamedu", "KMCH",
"அவிநாசி சாலையில்" all resolve to the right road. Areas and landmarks resolve to the road
they sit on (e.g. "PSG Tech" -> Avinashi Road).

How a match is scored (0-100):
- 100: the name/alias appears as whole words
- 97 : it appears when spaces are ignored ("avinashiroad", Tamil word + suffix)
- else: fuzzy similarity of nearby words (handles spelling mistakes)
"""
import re
import unicodedata
from functools import lru_cache

from rapidfuzz import fuzz

from modules.data_loader import load_all, load_places

ACCEPT_SCORE = 86   # at or above: we are confident
SUGGEST_SCORE = 72  # between: show as "Did you mean ...?"
ABBREVIATIONS = {"rd": "road", "ft": "feet", "jn": "junction", "jct": "junction", "hosp": "hospital"}
# words that say nothing about WHICH place it is; ignored when comparing spellings
GENERIC = {"road", "salai", "street", "junction", "signal", "main", "near", "stretch", "சாலை"}


def normalize(text):
    """Lowercase, drop punctuation, expand short forms, join spelled-out initials."""
    text = unicodedata.normalize("NFC", str(text)).lower()
    # punctuation and symbols -> space (keeps letters, digits and Tamil vowel signs)
    text = "".join(" " if unicodedata.category(ch)[0] in "PS" else ch for ch in text)
    text = re.sub(r"(\d)([a-z])", r"\1 \2", text)  # 100ft -> 100 ft
    text = re.sub(r"([a-z])(\d)", r"\1 \2", text)
    words = [ABBREVIATIONS.get(w, w) for w in text.split()]
    text = " ".join(words)
    # "r s puram" -> "rs puram", "d b road" -> "db road"
    while True:
        joined = re.sub(r"(?<![a-z])([a-z]) (?=[a-z](?![a-z]))", r"\1", text)
        if joined == text:
            return text
        text = joined


def _compact(text):
    return text.replace(" ", "")


def _core(words):
    return "".join(w for w in words if w not in GENERIC)


@lru_cache(maxsize=1)
def _index():
    """Every name a place can be called by -> (road_id, place name, kind)."""
    roads = load_all()["roads"]
    road_names = dict(zip(roads["road_id"], roads["name"]))
    entries = {}

    def add(alias, road_id, place, kind):
        norm = normalize(alias)
        if norm and (norm, road_id) not in entries:
            entries[(norm, road_id)] = {"alias": norm, "compact": _compact(norm), "core": _core(norm.split()),
                                        "road_id": road_id, "road_name": road_names[road_id],
                                        "place": place, "kind": kind}

    for road in roads.itertuples():
        for alias in [road.name] + list(road.aliases):
            add(alias, road.road_id, road.name, "road")
    for place in load_places().itertuples():
        for alias in [place.name, place.tamil] + list(place.aliases):
            if isinstance(alias, str):
                add(alias, place.road_id, place.name, place.kind)
    return list(entries.values())


def _fuzzy_score(words, entry):
    """Best similarity between the alias and any run of nearby words in the text.

    Generic words ("road", "signal" ...) are ignored on both sides, so "avinasi rd"
    is compared as "avinasi" vs "avinashi" and never matches "DB Road" just for "road".
    """
    target = entry["core"]
    if len(target) < 5:
        return 0  # too short to guess safely
    size = max(1, len([w for w in entry["alias"].split() if w not in GENERIC]))
    best = 0
    for n in {max(1, size - 1), size, size + 1}:
        for i in range(len(words) - n + 1):
            chunk = _core(words[i:i + n])
            if chunk and abs(len(chunk) - len(target)) <= 3:
                best = max(best, fuzz.ratio(chunk, target))
    return best


def find_places(text, limit=3):
    """Ranked matches: [{road_id, road_name, place, kind, alias, score}, ...] best first."""
    norm = normalize(text)
    if not norm:
        return []
    words, compact = norm.split(), _compact(norm)
    padded = f" {norm} "
    best = {}
    for entry in _index():
        if f" {entry['alias']} " in padded:
            score = 100
        elif len(entry["compact"]) >= 6 and entry["compact"] in compact:
            score = 97
        else:
            score = _fuzzy_score(words, entry)
        if score < SUGGEST_SCORE:
            continue
        key = (entry["road_id"], entry["place"])
        candidate = {**entry, "score": round(score)}
        old = best.get(key)
        if old is None or (candidate["score"], len(candidate["alias"])) > (old["score"], len(old["alias"])):
            best[key] = candidate
    ranked = sorted(best.values(), key=lambda m: (m["score"], len(m["alias"]), m["kind"] == "road"), reverse=True)
    # one entry per road, best first
    seen, out = set(), []
    for match in ranked:
        if match["road_id"] not in seen:
            seen.add(match["road_id"])
            out.append({k: match[k] for k in ["road_id", "road_name", "place", "kind", "alias", "score"]})
    return out[:limit]


def best_road(text):
    """(best match or None, suggestions). best is None when we are not confident enough."""
    matches = find_places(text)
    if matches and matches[0]["score"] >= ACCEPT_SCORE:
        return matches[0], matches[1:]
    return None, matches


if __name__ == "__main__":
    for msg in ["accident near avinasi rd", "Avinashiroad block", "R.S.Puram la traffic", "100ft road jam",
                "pelamedu signal", "hope collage", "near KMCH", "அவிநாசி சாலையில் விபத்து",
                "saravanapatti flood", "Something happened somewhere", "sathy"]:
        best, suggestions = best_road(msg)
        found = f"{best['road_name']} ({best['place']}, {best['score']})" if best else "—"
        hint = ", ".join(f"{s['place']} {s['score']}" for s in suggestions)
        print(f"{msg:32} -> {found:45} {hint}")
    print("places OK")
