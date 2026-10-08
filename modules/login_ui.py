"""Pieces shared by the public sign-in page (views/login.py) and the hidden admin console
(views/console.py): split-screen styles, the brand panel, Google config check, finishing sign-in."""
from html import escape

import streamlit as st

from modules import guards, ui

FEATURES = [("mic", "Report by voice"), ("insights", "See the impact"), ("bolt", "Fix in one click")]
ROUTES_SVG = """<svg class="lg-routes" viewBox="0 0 600 800" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
<path d="M-20 640 C110 590 170 500 260 470 S420 390 470 280 560 140 640 100"/>
<path d="M-20 320 C80 350 150 280 240 300 S380 380 450 350 600 270 640 290"/>
<path d="M90 840 C130 720 210 670 270 580 S340 440 430 420 540 440 640 380"/>
<circle cx="260" cy="470" r="5"/><circle cx="450" cy="350" r="5"/><circle cx="430" cy="420" r="6" class="amber"/></svg>"""


def google_configured():
    """True only for a real Google OIDC config in .streamlit/secrets.toml ([auth] + [auth.google])."""
    try:
        conf = st.secrets.get("auth", {})
        google = conf.get("google", conf)
        client_id = str(google.get("client_id", ""))
        return bool(client_id and not client_id.startswith("paste-") and conf.get("redirect_uri")
                    and conf.get("cookie_secret") and google.get("client_secret"))
    except Exception:
        return False


def finish(user, remember=False):
    guards.sign_in(user, remember=remember)
    st.rerun()


def page_css():
    dark = ui.is_dark()
    card_bg, card_border, muted = ("#161B22", "#2A313B", "#9CA3AF") if dark else ("#FFFFFF", "#E5E7EB", "#64748B")
    st.markdown(f"""<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], header[data-testid="stHeader"],
[data-testid="stToolbar"], [data-testid="stDecoration"] {{ display: none !important; }}
[data-testid="stMainBlockContainer"] {{ max-width: 100% !important; padding: 1rem 1.25rem !important; }}
.st-key-login_page > div > [data-testid="stHorizontalBlock"],
.st-key-login_page [data-testid="stHorizontalBlock"]:has(.lg-brand) {{ min-height: calc(100vh - 2rem); }}
.lg-brand {{ position: relative; overflow: hidden; border-radius: 22px; min-height: calc(100vh - 2rem); color: #fff;
  background:
    linear-gradient(rgba(147,197,253,.06) 1px, transparent 1px) 0 0 / 32px 32px,
    linear-gradient(90deg, rgba(147,197,253,.06) 1px, transparent 1px) 0 0 / 32px 32px,
    linear-gradient(150deg, #0B1E3F 0%, #102A5C 55%, #1D4ED8 120%);
  padding: 48px 52px; display: flex; flex-direction: column; justify-content: space-between; }}
.lg-routes {{ position: absolute; inset: 0; width: 100%; height: 100%; opacity: .28; }}
.lg-routes path {{ fill: none; stroke: #93C5FD; stroke-width: 2; stroke-dasharray: 8 12;
  animation: lg-dash 40s linear infinite; }}
.lg-routes circle {{ fill: #93C5FD; }} .lg-routes circle.amber {{ fill: #F59E0B; }}
@keyframes lg-dash {{ to {{ stroke-dashoffset: -600; }} }}
.lg-brand > :not(.lg-routes) {{ position: relative; }}
.lg-mark {{ display: flex; align-items: center; gap: 14px; font-weight: 800; letter-spacing: .08em; font-size: 24px; }}
.lg-mark svg {{ width: 48px; height: 48px; border-radius: 12px; box-shadow: 0 0 0 1px rgba(255,255,255,.12); }}
.lg-hero h1 {{ color: #fff; font-size: 44px; line-height: 1.08; font-weight: 800; letter-spacing: -.03em; margin: 0 0 14px;
  padding: 0; max-width: 520px; }}
.lg-hero p {{ color: #BFDBFE; font-size: 16px; margin: 0; max-width: 440px; }}
.lg-feats {{ list-style: none; padding: 0; margin: 32px 0 0; }}
.lg-feats li {{ display: flex; align-items: center; gap: 12px; margin-bottom: 14px; font-size: 16px; font-weight: 600;
  color: #EFF6FF; }}
.lg-feats .dp-ico {{ width: 38px; height: 38px; border-radius: 11px; background: rgba(255,255,255,.12); color: #fff;
  display: inline-flex; align-items: center; justify-content: center; font-size: 20px; }}
.lg-foot {{ color: #BFDBFE; font-size: 13px; opacity: .85; }}
.st-key-login_card {{ background: {card_bg}; border: 1px solid {card_border}; border-radius: 20px; max-width: 440px;
  width: 100%; margin: 0 auto; padding: 32px 32px 24px; box-shadow: 0 24px 48px rgba(15,23,42,.10),
  0 2px 6px rgba(15,23,42,.06); animation: lg-in .25s ease-out both; }}
@keyframes lg-in {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: none; }} }}
.st-key-login_card p.lg-title {{ font-size: 28px; font-weight: 750; letter-spacing: -.02em; margin: 0; line-height: 1.2; }}
.st-key-login_card p.lg-sub {{ color: {muted}; margin: 4px 0 16px; font-size: 15px; }}
.st-key-login_card button {{ min-height: 48px; font-weight: 600; border-radius: 12px; }}
.st-key-login_card input {{ min-height: 46px; }}
.st-key-login_card button:focus-visible, .st-key-login_card input:focus-visible {{ outline: 3px solid #93C5FD; }}
.lg-or {{ display: flex; align-items: center; gap: 12px; color: {muted}; font-size: 13px; margin: 4px 0 8px; }}
.lg-or::before, .lg-or::after {{ content: ""; flex: 1; height: 1px; background: {card_border}; }}
.lg-link a {{ color: #2563EB; text-decoration: none; font-weight: 600; font-size: 14px; }}
.lg-link {{ text-align: right; margin-top: 6px; }}
.lg-demo {{ font-size: 11px; font-weight: 800; letter-spacing: .06em; color: #92400E; background: #FEF3C7;
  border-radius: 999px; padding: 2px 9px; margin-right: 6px; }}
.st-key-login_page .st-key-login_card [data-testid="stHorizontalBlock"] {{ min-height: auto; flex-direction: row;
  flex-wrap: nowrap; align-items: center; gap: .5rem; }}
.st-key-login_page .st-key-login_card [data-testid="stColumn"] {{ width: auto !important; min-width: 0;
  flex: 1 1 0 !important; }}
.st-key-google_btn button p::before {{ content: ""; display: inline-block; width: 18px; height: 18px; margin-right: 10px;
  vertical-align: -3px; background: url("{GOOGLE_G}") no-repeat center / contain; }}
.lg-console {{ background: #0B1E3F; color: #F8FAFC; border-radius: 14px; padding: 14px 16px; margin-bottom: 16px;
  font-weight: 700; display: flex; gap: 12px; align-items: center; }}
.lg-console svg {{ width: 34px; height: 34px; border-radius: 9px; }}
.lg-console small {{ display: block; font-weight: 500; color: #94A3B8; font-size: 13px; }}
@media (max-width: 768px) {{
  .st-key-login_page [data-testid="stHorizontalBlock"]:has(.lg-brand) {{ flex-direction: column; min-height: auto; gap: .75rem; }}
  .st-key-login_page [data-testid="stHorizontalBlock"]:has(.lg-brand) > [data-testid="stColumn"] {{ width: 100% !important;
    flex: 1 1 100% !important; }}
  .lg-brand {{ min-height: auto; padding: 18px 20px; border-radius: 16px; }}
  .lg-mark {{ font-size: 18px; }} .lg-mark svg {{ width: 36px; height: 36px; }}
  .lg-hero h1 {{ font-size: 20px; margin: 10px 0 0; }} .lg-hero p, .lg-feats, .lg-foot {{ display: none; }}
  [data-testid="stMainBlockContainer"] {{ padding: .75rem 1rem !important; }}
  .st-key-login_card {{ padding: 22px 18px 16px; border-radius: 18px; box-shadow: none; }}
}}
@media (prefers-reduced-motion: reduce) {{ .lg-routes path, .st-key-login_card {{ animation: none; }} }}
</style>""", unsafe_allow_html=True)


def brand_panel():
    feats = "".join(f"<li>{ui.icon(name)}{escape(text)}</li>" for name, text in FEATURES)
    st.markdown(f"""<div class="lg-brand">{ROUTES_SVG}
<div><div class="lg-mark">{ui.MARK_SVG}<span>{ui.APP_NAME}</span></div>
<div class="lg-hero" style="margin-top:56px"><h1>{escape(ui.TAGLINE)}</h1>
<p>Disruption-Aware Logistics Decision Support System</p>
<ul class="lg-feats">{feats}</ul></div></div>
<div class="lg-foot">HackNext'26 · {escape(ui.TEAM_NAME)}</div></div>""", unsafe_allow_html=True)


GOOGLE_G = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'>"
            "<path fill='%23FFC107' d='M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 "
            "12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3"
            "-.1-2.4-.4-3.5z'/><path fill='%23FF3D00' d='M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 "
            "3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z'/><path fill='%234CAF50' d='M24 44c5.2 0 9.9-2 "
            "13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z'/>"
            "<path fill='%231976D2' d='M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24"
            "c0-1.3-.1-2.4-.4-3.5z'/></svg>")
