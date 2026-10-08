"""Shared Streamlit building blocks so both screens look and behave the same."""
import time
from datetime import date
from html import escape
from pathlib import Path

import streamlit as st

from modules import guards, store
from modules.data_loader import NOW_MIN, min_to_hhmm
from modules.parser import setting

CSS_PATH = Path(__file__).resolve().parent.parent / "assets" / "style.css"
TEAM_NAME = setting("TEAM_NAME", "Team Ripple")  # shown on the home page; set TEAM_NAME in secrets to change
BRAND = "#2563EB"
RISK_CLASS = {"Critical": "rp-critical", "High": "rp-high", "Medium": "rp-medium", "Low": "rp-low"}
RISK_HEX = {"Critical": "#DC2626", "High": "#EA580C", "Medium": "#CA8A04", "Low": "#16A34A", "On track": "#64748B"}
SEVERITY_CLASS = {"critical": "rp-critical", "high": "rp-high", "medium": "rp-medium", "low": "rp-low"}
PARTNER_STATUS = {"on_duty": ("On duty", "rp-low", "#16A34A"), "standby": ("Standby", "rp-brand", "#2563EB"),
                  "on_break": ("On break", "rp-medium", "#CA8A04"), "off_duty": ("Off duty", "rp-neutral", "#6B7280")}
ISSUE_STATUS = {"new": ("Needs location", "rp-medium"), "analysed": ("Waiting for decision", "rp-high"),
                "accepted": ("Plan applied", "rp-low"), "rejected": ("Rejected", "rp-neutral")}
ACTION_LABELS = {"reassign": ("Reassign to backup", "#DC2626"), "reroute": ("Reroute vehicle", "#EA580C"),
                 "resequence": ("Prioritise stop", "#CA8A04"), "reschedule_notify": ("Notify customer", "#16A34A")}


ROLE_BADGES = {"super_admin": ("Super Admin", "rp-super", "#7C3AED"),
               "branch_admin": ("Branch Admin", "rp-brand", BRAND),
               "partner": ("Delivery Partner", "rp-low", "#16A34A")}
LOGO_SMALL = ('<svg width="28" height="28" viewBox="0 0 40 40" aria-hidden="true"><rect width="40" height="40" rx="11" '
              'fill="#2563EB"/><path d="M7 21c3.5 0 3.5-4 7-4s3.5 4 7 4 3.5-4 7-4 3.5 4 5 4" stroke="#fff" '
              'stroke-width="2.6" fill="none" stroke-linecap="round"/><path d="M7 28c3.5 0 3.5-4 7-4s3.5 4 7 4 '
              '3.5-4 7-4 3.5 4 5 4" stroke="#BFDBFE" stroke-width="2.6" fill="none" stroke-linecap="round"/></svg>')


def setup_store():
    store.init_db()


def setup_page(layout="wide"):
    # auto: the menu is open on laptops and folded away on phones
    st.set_page_config(page_title="RIPPLE", page_icon=":material/route:", layout=layout,
                       initial_sidebar_state="auto")
    st.markdown(f"<style>{CSS_PATH.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)


def is_dark():
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


def clock_text():
    return f"{date.today().strftime('%a %d %b')} · {min_to_hhmm(NOW_MIN)} (simulated)"


def header(title, subtitle="", live=True):
    """Page title; branch admins also see their branch name (e.g. 'Coimbatore East – Peelamedu')."""
    live_dot = '<span class="rp-live"></span>' if live else ""
    branch = st.session_state.get("branch_name") if st.session_state.get("role") == "branch_admin" else None
    branch_chip = f'<span class="rp-badge rp-brand" style="margin-right:8px">{escape(branch)}</span>' if branch else ""
    st.markdown(
        f'<div class="rp-header"><div><p class="rp-title">{escape(title)}</p>'
        f'{f"<p class=rp-sub>{escape(subtitle)}</p>" if subtitle else ""}</div>'
        f'<div class="rp-clock">{branch_chip}{live_dot}{escape(clock_text())}</div></div>', unsafe_allow_html=True)


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


def sidebar_user():
    """Logo, who is signed in (role badge, branch), the clock, Logout – Reset demo data for Super Admins only."""
    user = st.session_state["user"]
    label, css, colour = ROLE_BADGES[user["role"]]
    line = user.get("email") or user["user_id"]
    if user["role"] == "partner":
        from modules import partner_scope

        profile = partner_scope.get_partner_profile(user["dp_id"], user["branch_id"])
        line = f"{user['dp_id']} · {profile['vehicle_type'].title()} {profile['reg_no']}"
    with st.sidebar:
        st.markdown(f'<div class="rp-side-logo">{LOGO_SMALL}<span>RIPPLE</span></div>', unsafe_allow_html=True)
        st.markdown(f'<div class="rp-person"><div class="rp-avatar" style="background:{colour}">'
                    f'{escape(initials(user["display_name"]))}</div><div><b>{escape(user["display_name"])}</b><br>'
                    f'<small>{escape(line)}</small></div></div><div style="margin:8px 0 2px">{badge(label, css)}</div>'
                    + (f'<small style="opacity:.7">{escape(user["branch_name"])}</small>' if user.get("branch_name") else ""),
                    unsafe_allow_html=True)
        st.caption(f":material/schedule: {clock_text()}")
        if st.button("Logout", icon=":material/logout:", width="stretch", key="logout"):
            guards.logout()
        if user["role"] == "super_admin":
            with st.popover("Reset demo data", icon=":material/restart_alt:", width="stretch"):
                st.write("Back to 09:00 in every branch: no issues, all deliveries pending, demo accounts restored. "
                         "Everyone using the app sees the reset and is signed out.")
                if st.button("Reset everything", type="primary", key="reset_demo"):
                    store.reset_demo()
                    guards.logout()


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
