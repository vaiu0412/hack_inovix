"""Shared Streamlit building blocks so both screens look and behave the same."""
import time
from datetime import date
from html import escape
from pathlib import Path

import streamlit as st

from modules import store
from modules.data_loader import NOW_MIN, min_to_hhmm

CSS_PATH = Path(__file__).resolve().parent.parent / "assets" / "style.css"
RISK_CLASS = {"Critical": "rp-critical", "High": "rp-high", "Medium": "rp-medium", "Low": "rp-low"}
RISK_HEX = {"Critical": "#DC2626", "High": "#EA580C", "Medium": "#CA8A04", "Low": "#16A34A", "On track": "#64748B"}
SEVERITY_CLASS = {"critical": "rp-critical", "high": "rp-high", "medium": "rp-medium", "low": "rp-low"}
PARTNER_STATUS = {"on_duty": ("On duty", "rp-low", "#16A34A"), "standby": ("Standby", "rp-brand", "#0F9488"),
                  "on_break": ("On break", "rp-medium", "#CA8A04"), "off_duty": ("Off duty", "rp-neutral", "#6B7280")}
ISSUE_STATUS = {"new": ("Needs location", "rp-medium"), "analysed": ("Waiting for decision", "rp-high"),
                "accepted": ("Plan applied", "rp-low"), "rejected": ("Rejected", "rp-neutral")}
ACTION_LABELS = {"reassign": ("Reassign to backup", "#DC2626"), "reroute": ("Reroute vehicle", "#EA580C"),
                 "resequence": ("Prioritise stop", "#CA8A04"), "reschedule_notify": ("Notify customer", "#16A34A")}


def setup_page(layout="wide"):
    # collapsed: on phones the navigation menu must not cover the page on every load
    st.set_page_config(page_title="Ripple", page_icon=":material/route:", layout=layout,
                       initial_sidebar_state="collapsed")
    st.markdown(f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)
    store.init_db()


def is_dark():
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


def clock_text():
    return f"{date.today().strftime('%a %d %b')} · {min_to_hhmm(NOW_MIN)} (simulated)"


def header(title, subtitle="", live=True):
    live_dot = '<span class="rp-live"></span>' if live else ""
    st.markdown(
        f'<div class="rp-header"><div><p class="rp-title">{escape(title)}</p>'
        f'{f"<p class=rp-sub>{escape(subtitle)}</p>" if subtitle else ""}</div>'
        f'<div class="rp-clock">{live_dot}{escape(clock_text())}</div></div>', unsafe_allow_html=True)


def badge(text, css="rp-neutral"):
    return f'<span class="rp-badge {css}">{escape(str(text))}</span>'


def risk_badge(label):
    return badge(label, RISK_CLASS.get(label, "rp-neutral"))


def severity_badge(severity):
    return badge(str(severity).capitalize(), SEVERITY_CLASS.get(severity, "rp-neutral"))


def partner_badge(status):
    text, css, _ = PARTNER_STATUS.get(status, (status, "rp-neutral", "#6B7280"))
    return badge(text, css)


def issue_badge(status):
    text, css = ISSUE_STATUS.get(status, (status, "rp-neutral"))
    return badge(text, css)


def initials(name):
    return "".join(part[0] for part in str(name).split()[:2]).upper()


def person(name, line, status="on_duty"):
    colour = PARTNER_STATUS.get(status, ("", "", "#6B7280"))[2]
    return (f'<div class="rp-person"><div class="rp-avatar" style="background:{colour}">{escape(initials(name))}</div>'
            f'<div><b>{escape(name)}</b><br><small>{escape(line)}</small></div></div>')


def kv(items):
    """Small label/value grid: kv([("Vehicle", "V1"), ...])"""
    cells = "".join(f"<div><small>{escape(str(k))}</small><span>{v}</span></div>" for k, v in items)
    return f'<div class="rp-kv">{cells}</div>'


def ai_note(text, title="AI dispatcher"):
    st.markdown(f'<div class="rp-note"><b>{escape(title)}</b>{escape(text)}</div>', unsafe_allow_html=True)


def actions_list(actions):
    rows = []
    for a in actions:
        label, colour = ACTION_LABELS.get(a["action_type"], (a["action_type"], "#6B7280"))
        rows.append(f'<div class="rp-action"><span class="rp-dot" style="background:{colour}"></span><div>'
                    f'<b>{escape(label)}</b> · {escape(a["description"])}<small>{escape(a["why"])}</small></div></div>')
    st.markdown("".join(rows), unsafe_allow_html=True)


def kpi_row(items, tile_width=170):
    """KPI tiles that sit in one row on a laptop and wrap 2-3 per row on a phone.

    items: [(label, value, delta_or_None), ...]
    """
    with st.container(horizontal=True, gap="small"):
        for label, value, delta in items:
            st.metric(label, value, delta, delta_color="off", delta_arrow="off", border=True, width=tile_width)


def before_after(before, after):
    return (f'<span class="rp-ba"><span class="before">{before}</span><span class="arrow">→</span>'
            f'<span class="after">{after}</span></span>')


def pause_live_updates(seconds=180):
    """Hold auto-refresh while someone is typing or recording (a rerun would clear the form)."""
    st.session_state["_pause_until"] = time.time() + seconds


def resume_live_updates():
    st.session_state.pop("_pause_until", None)


def live_updates(every="4s"):
    """Re-run the page when anything changes in the shared database (another device acted)."""
    st.session_state["_seen_version"] = store.version()

    @st.fragment(run_every=every)
    def _watch():
        if time.time() < st.session_state.get("_pause_until", 0):
            return
        if store.version() != st.session_state.get("_seen_version"):
            st.rerun()

    _watch()
