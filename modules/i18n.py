"""Tamil + English for the partner app. Texts live in i18n/en.json and i18n/ta.json (same keys); t("key", n=3)
returns the text in the signed-in user's language, falling back to English. The choice is saved per user
(user_prefs, key "lang") like the other preferences. Admin pages stay in English."""
import json
from functools import lru_cache
from pathlib import Path

import streamlit as st

FOLDER = Path(__file__).resolve().parent.parent / "i18n"
LANGS = {"en": "English", "ta": "தமிழ்"}


@lru_cache(maxsize=4)
def texts(lang):
    """All texts of one language ({} if the file is missing)."""
    try:
        return json.loads((FOLDER / f"{lang}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def lang():
    """The current user's language: 'en' or 'ta'."""
    value = st.session_state.get("lang", "en")
    return value if value in LANGS else "en"


def t(key, **values):
    """The text for `key` in the current language (English if missing), with {placeholders} filled in."""
    text = texts(lang()).get(key) or texts("en").get(key) or key
    return text.format(**values) if values else text


def load(user):
    """First run after sign-in: the user's saved language (the menu titles need it before the sidebar)."""
    if "lang" not in st.session_state:
        from modules import store

        saved = store.get_prefs(user["user_id"]).get("lang")
        st.session_state["lang"] = saved if saved in LANGS else "en"


def picker():
    """English / தமிழ் switch (saved with the user's preferences)."""
    st.segmented_control("Language", list(LANGS), format_func=LANGS.get, key="lang", label_visibility="collapsed")
