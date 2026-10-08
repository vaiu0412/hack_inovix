"""DEPORT design system for Streamlit: page shell, cards, KPI tiles, status pills, empty states,
skeletons and the sidebar. Every screen uses these, so all roles look and read the same."""
import time
from datetime import date
from html import escape
from pathlib import Path

import streamlit as st

from modules import guards, store
from modules.data_loader import NOW_MIN, min_to_hhmm
from modules.parser import setting

ASSETS = Path(__file__).resolve().parent.parent / "assets"
CSS_PATH = ASSETS / "style.css"
LOGO_PATH, MARK_PATH, FAVICON_PATH = ASSETS / "logo.svg", ASSETS / "logo_mark.svg", ASSETS / "favicon.png"
APP_NAME = "DEPORT"
APP_TITLE = "DEPORT – Disruption-Aware Logistics Decision Support System"
TAGLINE = "From Disruption to Decision."
TEAM_NAME = setting("TEAM_NAME", "Team DEPORT")  # sign-in page footer; set TEAM_NAME in secrets to change
MARK_SVG = MARK_PATH.read_text(encoding="utf-8").split("-->", 1)[-1].strip()
MARK_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" aria-hidden="true">' + MARK_SVG
BRAND, NAVY, AMBER = "#2563EB", "#0B1E3F", "#F59E0B"

# one status language everywhere: key -> (word, css class, dot colour, emoji for tables/tooltips)
STATUS = {
    "normal": ("Normal", "dp-s-normal", "#16A34A", "🟢"),
    "delayed": ("Delayed", "dp-s-delayed", "#EAB308", "🟡"),
    "critical": ("Critical", "dp-s-critical", "#DC2626", "🔴"),
    "available": ("Available", "dp-s-available", "#2563EB", "🔵"),
    "break": ("Break", "dp-s-off", "#94A3B8", "⚪"),
    "off": ("Off", "dp-s-off", "#94A3B8", "⚪"),
    "done": ("Done", "dp-s-normal", "#16A34A", "✅"),
}
RISK_STATE = {"Critical": "critical", "High": "delayed", "Medium": "delayed", "Low": "normal"}
RISK_HEX = {"Critical": "#DC2626", "High": "#CA8A04", "Medium": "#CA8A04", "Low": "#16A34A", "On track": "#64748B"}
VEHICLE_EMOJI = {"bike": "🏍️", "car": "🚗", "van": "🚐", "truck": "🚚"}
VEHICLE_ICON = {"bike": ":material/two_wheeler:", "car": ":material/directions_car:", "van": ":material/airport_shuttle:",
                "truck": ":material/local_shipping:"}
PARTNER_STATUS = {"on_duty": ("On duty", "rp-low", "#16A34A"), "standby": ("Standby", "rp-brand", "#2563EB"),
                  "on_break": ("Break", "rp-neutral", "#94A3B8"), "off_duty": ("Off", "rp-neutral", "#94A3B8")}
ISSUE_STATUS = {"new": ("Needs place", "delayed"), "analysed": ("Waiting", "critical"),
                "accepted": ("Plan applied", "normal"), "rejected": ("Rejected", "off")}
ROLE_BADGES = {"super_admin": ("Super Admin", "rp-super", "#7C3AED"),
               "branch_admin": ("Branch Admin", "rp-brand", BRAND),
               "partner": ("Partner", "rp-low", "#16A34A")}


# ---------------------------------------------------------------- page shell
def setup_store():
    store.init_db()


def setup_page(layout="wide", role=None):
    st.set_page_config(page_title=APP_NAME, page_icon=str(FAVICON_PATH), layout=layout,
                       initial_sidebar_state="auto")  # menu open on laptops, folded on phones
    extra = ""
    if layout == "wide":  # admin: dense desktop dashboard, max 1400px
        extra += '[data-testid="stMainBlockContainer"] { max-width: 1400px; }'
    if role == "partner":  # mobile-first: one column, thumb-sized buttons
        extra += (".stButton button, .stFormSubmitButton button, .stLinkButton a, .stDownloadButton button "
                  "{ min-height: 52px; font-size: 16px; border-radius: 14px; }")
    if is_dark():
        extra += (":root { --dp-bg:#0D1117; --dp-card:#161B22; --dp-border:#2A313B; --dp-text:#E6EDF3; --dp-muted:#9CA3AF;"
                  " --dp-ink-normal:#4ADE80; --dp-ink-delayed:#FACC15; --dp-ink-critical:#F87171; --dp-ink-available:#60A5FA;"
                  " --dp-ink-off:#CBD5E1; --dp-shadow:none; --dp-shadow-hover:0 8px 24px rgba(0,0,0,.35); }"
                  ".dp-skel { background: linear-gradient(90deg,#1B212A 25%,#232B36 37%,#1B212A 63%); background-size:400% 100%; }"
                  ".st-key-alert_banner { background: rgba(220,38,38,.12); border-color: rgba(220,38,38,.4); }"
                  ".dp-alert { color: #FCA5A5; }")
    st.markdown(f"<style>{CSS_PATH.read_text(encoding='utf-8')}{extra}</style>", unsafe_allow_html=True)
    st.session_state["_card_n"] = 0


def is_dark():
    try:
        return st.context.theme.type == "dark"
    except Exception:
        return False


def clock_text():
    return f"{date.today().strftime('%a %d %b')} · {min_to_hhmm(NOW_MIN)}"


def header(title, subtitle="", live=True):
    """Logo + 1-3 word title (+ short subtitle). Branch admins also see their branch."""
    branch = st.session_state.get("branch_name") if st.session_state.get("role") == "branch_admin" else None
    meta = pill_html("available", branch.split(" – ")[0]) if branch else ""
    meta += f'<span>{"<span class=dp-live></span> " if live else ""}{escape(clock_text())}</span>'
    sub = f'<p class="dp-sub">{escape(subtitle)}</p>' if subtitle else ""
    st.markdown(f'<div class="dp-header"><div class="t">{MARK_SVG}<div><p class="dp-h1">{escape(title)}</p>{sub}'
                f'</div></div><div class="dp-meta">{meta}</div></div>', unsafe_allow_html=True)


def section(title, icon_name=None):
    ico = icon(icon_name) if icon_name else ""
    st.markdown(f'<p class="dp-h2">{ico}{escape(title)}</p>', unsafe_allow_html=True)


def step(number, title):
    st.markdown(f'<div class="dp-step"><b>{number}</b>{escape(title)}</div>', unsafe_allow_html=True)


def card(name=None, **kwargs):
    """A design-system card (bordered container, radius 14, soft shadow, 20px padding)."""
    if name is None:
        st.session_state["_card_n"] = st.session_state.get("_card_n", 0) + 1
        name = str(st.session_state["_card_n"])
    return st.container(border=True, key=f"card_{name}", **kwargs)


def icon(name, size=None):
    style = f' style="font-size:{size}px"' if size else ""
    return f'<span class="dp-ico" aria-hidden="true"{style}>{escape(name)}</span>'


# ---------------------------------------------------------------- status language
def risk_state(label):
    return RISK_STATE.get(label, "normal")


def partner_state(status, worst_risk=None):
    """Partner status for maps and tables: Available / Break / Off, else Normal / Delayed / Critical by risk."""
    if status == "standby":
        return "available"
    if status == "on_break":
        return "break"
    if status == "off_duty":
        return "off"
    return risk_state(worst_risk) if worst_risk else "normal"


def pill_html(state, text=None):
    word, css, _, _ = STATUS.get(state, STATUS["off"])
    return f'<span class="dp-pill {css}"><i></i>{escape(text or word)}</span>'


def status_text(state):
    """'🟢 Normal' – coloured status for dataframes."""
    word, _, _, emoji = STATUS.get(state, STATUS["off"])
    return f"{emoji} {word}"


def issue_pill(status):
    word, state = ISSUE_STATUS.get(status, (status, "off"))
    return pill_html(state, word)


def badge(text, css="rp-neutral"):
    return f'<span class="rp-badge {css}">{escape(str(text))}</span>'


def risk_badge(label):
    return pill_html(risk_state(label), label)


def severity_badge(severity):
    state = {"critical": "critical", "high": "critical", "medium": "delayed"}.get(severity, "normal")
    return pill_html(state, str(severity).capitalize())


def partner_badge(status):
    return pill_html(partner_state(status))


def issue_badge(status):
    return issue_pill(status)


# ---------------------------------------------------------------- building blocks
def initials(name):
    return "".join(part[0] for part in str(name).split()[:2]).upper()


def person(name, line, colour="#2563EB"):
    return (f'<div class="dp-person"><div class="dp-avatar" style="background:{colour}">{escape(initials(name))}</div>'
            f'<div><b>{escape(name)}</b><br><small>{escape(line)}</small></div></div>')


def kv(items):
    """Short label / value grid: kv([("Vehicle", "V1"), ...]). Values may contain HTML."""
    cells = "".join(f"<div><small>{escape(str(k))}</small><span>{v}</span></div>" for k, v in items)
    return f'<div class="dp-kv">{cells}</div>'


def kpi_cards(items):
    """KPI tiles: [(icon, value, label, trend or None, tone or None)]; whole numbers count up (pure CSS)."""
    tiles = []
    for item in items:
        icon_name, value, label, trend, tone = (list(item) + [None, None])[:5]
        if isinstance(value, (int,)) and not isinstance(value, bool) and value >= 0:
            number = (f'<span class="dp-count" style="--to:{value}" aria-hidden="true"></span>'
                      f'<span class="dp-sr">{value}</span>')
        else:
            number = escape(str(value))
        trend_html = f'<div class="trend">{escape(str(trend))}</div>' if trend else ""
        tiles.append(f'<div class="dp-kpi tone-{tone or "primary"}{" hot" if tone == "critical" and value else ""}">'
                     f'<span class="chip">{icon(icon_name)}</span><div class="num">{number}</div>'
                     f'<div class="lbl">{escape(label)}</div>{trend_html}</div>')
    st.markdown(f'<div class="dp-kpis">{"".join(tiles)}</div>', unsafe_allow_html=True)


def kpi_row(items, tile_width=None):
    """Older call style: [(label, value, trend)]."""
    kpi_cards([("insights", value, label, trend, None) for label, value, trend in items])


def empty_state(icon_name, text, button=None, key=None, **button_kwargs):
    """Icon + one line (+ one button). Returns True when the button was clicked."""
    st.markdown(f'<div class="dp-empty">{icon(icon_name)}<p>{escape(text)}</p></div>', unsafe_allow_html=True)
    if button:
        _, mid, _ = st.columns([1, 2, 1])
        return mid.button(button, key=key, width="stretch", **button_kwargs)
    return False


def skeleton(height=160, count=1):
    """Shimmer placeholders while the map or data loads (put them in st.empty, then replace)."""
    block = f'<div class="dp-skel" style="height:{height}px;margin-bottom:12px"></div>'
    return block * count


def progress_ring(done, total, size=84):
    share = done / total if total else 0
    r, c = 34, 2 * 3.14159 * 34
    return (f'<div class="dp-ring"><svg width="{size}" height="{size}" viewBox="0 0 84 84" role="img" '
            f'aria-label="{done} of {total} delivered"><circle cx="42" cy="42" r="{r}" fill="none" '
            f'stroke="var(--dp-border)" stroke-width="9"/><circle cx="42" cy="42" r="{r}" fill="none" '
            f'stroke="#16A34A" stroke-width="9" stroke-linecap="round" stroke-dasharray="{c * share:.1f} {c:.1f}" '
            f'transform="rotate(-90 42 42)"/><text x="42" y="47" text-anchor="middle" font-size="17" font-weight="750" '
            f'fill="var(--dp-text)">{done}/{total}</text></svg><div><div class="n">{done} of {total}</div>'
            f'<div class="dp-small">delivered</div></div></div>')


def before_after(rows):
    """[(label, before, after), ...] -> the Before → After strip shown after a plan is applied."""
    cells = "".join(f'<div><small>{escape(label)}</small><span class="v"><span class="b">{escape(str(b))}</span>'
                    f'<span class="arr">→</span><span class="f">{escape(str(a))}</span></span></div>'
                    for label, b, a in rows)
    st.markdown(f'<div class="dp-ba">{cells}</div>', unsafe_allow_html=True)


def rec_card(action):
    """One recommendation: Action / Why (2 short lines) / Impact."""
    title = action.get("title") or action["description"]
    why = action.get("why_short") or action["why"]
    impact = action.get("impact_short") or ""
    return (f'<div class="dp-rec k-{escape(action["action_type"])}"><div class="a">{escape(title)}</div>'
            f'<div class="w">{escape(why)}</div><div class="i">{escape(impact)}</div></div>')


# ---------------------------------------------------------------- live refresh
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


# ---------------------------------------------------------------- sidebar
def sidebar_user():
    """Logo, who is signed in (role, branch), Logout – and Reset demo for Super Admins only."""
    user = st.session_state["user"]
    label, css, colour = ROLE_BADGES[user["role"]]
    line = user.get("email") or user["user_id"]
    if user["role"] == "partner":
        from modules import partner_scope

        profile = partner_scope.get_partner_profile(user["dp_id"], user["branch_id"])
        line = f"{user['dp_id']} · {VEHICLE_EMOJI.get(profile['vehicle_type'], '')} {profile['reg_no']}"
    st.logo(str(LOGO_PATH), icon_image=str(MARK_PATH), size="large")
    with st.sidebar:
        st.markdown(person(user["display_name"], line, colour)
                    + f'<div style="margin:10px 0 2px">{badge(label, css)}</div>'
                    + (f'<small style="color:var(--dp-muted)">{escape(user["branch_name"])}</small>'
                       if user.get("branch_name") else ""), unsafe_allow_html=True)
        if st.button("Sign out", icon=":material/logout:", width="stretch", key="logout"):
            guards.logout()
        if user["role"] == "super_admin":
            with st.popover("Reset demo", icon=":material/restart_alt:", width="stretch"):
                st.caption("Back to 09:00. Everyone is signed out.")
                if st.button("Reset now", type="primary", key="reset_demo", width="stretch"):
                    store.reset_demo()
                    guards.logout()
