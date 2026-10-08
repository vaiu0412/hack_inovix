"""Pieces shared by the public sign-in page (views/login.py) and the unlisted admin console (views/console.py):
full-screen dark backdrop with slow route lines, the glowing logo header, the glass card, Google config check,
finishing sign-in."""
from html import escape

import streamlit as st

from modules import guards, ui
from modules.parser import setting

FEATURES = [("mic", "Report by voice"), ("insights", "See the impact"), ("bolt", "Fix in one click")]
ROUTES_SVG = """<svg viewBox="0 0 1200 800" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
<path d="M-40 640 C180 560 300 470 470 450 S760 380 860 260 1080 120 1260 90"/>
<path d="M-40 300 C140 340 260 270 420 290 S700 380 830 350 1100 250 1260 280"/>
<path d="M160 860 C220 720 360 660 470 570 S620 430 790 410 1010 440 1260 360"/>
<path d="M-40 120 C220 160 420 80 640 140 S980 220 1260 160"/>
<circle cx="470" cy="450" r="5"/><circle cx="830" cy="350" r="5"/><circle cx="790" cy="410" r="6" class="amber"/>
<circle cx="640" cy="140" r="4"/></svg>"""


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


def demo_mode():
    """'Quick demo access' chips for judges – only when DEMO_MODE=true (secrets or environment). Off by default."""
    return str(setting("DEMO_MODE", "false")).strip().lower() in ("1", "true", "yes", "on")


def finish(user, remember=False):
    guards.sign_in(user, remember=remember)
    st.rerun()


def page_css():
    st.markdown(f"""<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], header[data-testid="stHeader"],
[data-testid="stToolbar"], [data-testid="stDecoration"] {{ display: none !important; }}
[data-testid="stMainBlockContainer"] {{ max-width: 100% !important; padding: 1rem 1.25rem 2rem !important; }}
.lg-bg {{ position: fixed; inset: 0; z-index: 0; pointer-events: none; overflow: hidden;
  background:
    linear-gradient(rgba(148,163,184,.05) 1px, transparent 1px) 0 0 / 40px 40px,
    linear-gradient(90deg, rgba(148,163,184,.05) 1px, transparent 1px) 0 0 / 40px 40px; }}
.lg-bg svg {{ position: absolute; inset: 0; width: 100%; height: 100%; opacity: .5; }}
.lg-bg path {{ fill: none; stroke: #60A5FA; stroke-opacity: .35; stroke-width: 2;
  stroke-dasharray: 8 14; animation: lg-dash 50s linear infinite; }}
.lg-bg circle {{ fill: #60A5FA; filter: drop-shadow(0 0 6px #60A5FA); }} .lg-bg circle.amber {{ fill: #F59E0B;
  filter: drop-shadow(0 0 8px #F59E0B); }}
@keyframes lg-dash {{ to {{ stroke-dashoffset: -880; }} }}
.st-key-login_head, .st-key-login_card {{ position: relative; z-index: 1; max-width: 440px; width: 100%; margin-left: auto !important;
  margin-right: auto !important; }}
.st-key-login_head {{ margin-top: 6vh; text-align: center; align-items: center; }}
.st-key-login_head [data-testid="stMarkdownContainer"], .st-key-login_head p {{ text-align: center !important; }}
.lg-mark {{ display: inline-flex; align-items: center; gap: 14px; font-weight: 800; letter-spacing: .08em; font-size: 26px;
  color: #F8FAFC; }}
.lg-mark svg {{ width: 52px; height: 52px; border-radius: 14px; animation: lg-glow 4s ease-in-out infinite alternate; }}
@keyframes lg-glow {{ from {{ filter: drop-shadow(0 0 8px rgba(59,130,246,.45)); }}
  to {{ filter: drop-shadow(0 0 18px rgba(124,58,237,.6)); }} }}
.lg-tag {{ color: #F8FAFC; font-size: 22px; font-weight: 750; letter-spacing: -.01em; margin: 14px 0 4px; }}
.lg-sub {{ color: #94A3B8; font-size: 14px; margin: 0 0 14px; }}
.lg-feats {{ display: flex; gap: 8px; justify-content: center; flex-wrap: wrap; margin: 0 0 18px; }}
.lg-feats span {{ display: inline-flex; align-items: center; gap: 6px; padding: 5px 11px; border-radius: 999px; font-size: 12.5px;
  font-weight: 600; color: #CBD5E1; background: rgba(255,255,255,.06); border: 1px solid rgba(255,255,255,.12); }}
.lg-feats .dp-ico {{ font-size: 16px; color: #93C5FD; }}
.st-key-login_card {{ background: rgba(255,255,255,.07) !important; border: 1px solid rgba(255,255,255,.14);
  border-radius: 22px; padding: 28px 28px 20px; backdrop-filter: blur(18px) saturate(140%);
  -webkit-backdrop-filter: blur(18px) saturate(140%); box-shadow: 0 20px 60px rgba(0,0,0,.45), 0 0 0 1px rgba(255,255,255,.02);
  animation: lg-in .25s ease-out both; }}
@keyframes lg-in {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: none; }} }}
.st-key-login_card p.lg-title {{ font-size: 26px; font-weight: 750; letter-spacing: -.02em; margin: 0; line-height: 1.2; color: #F8FAFC; }}
.st-key-login_card p.lg-sub2 {{ color: #94A3B8; margin: 4px 0 16px; font-size: 15px; }}
.st-key-login_card button {{ min-height: 48px; font-weight: 600; border-radius: 12px; }}
.st-key-login_card input {{ min-height: 46px; }}
.lg-or {{ display: flex; align-items: center; gap: 12px; color: #94A3B8; font-size: 13px; margin: 4px 0 8px; }}
.lg-or::before, .lg-or::after {{ content: ""; flex: 1; height: 1px; background: rgba(255,255,255,.12); }}
.lg-link a {{ color: #93C5FD; text-decoration: none; font-weight: 600; font-size: 14px; }}
.lg-link {{ text-align: right; margin-top: 6px; }}
.lg-foot {{ position: relative; z-index: 1; text-align: center; color: #64748B; font-size: 12px; margin-top: 18px; }}
.lg-demo {{ font-size: 11px; font-weight: 800; letter-spacing: .08em; color: #FDE68A; margin: 14px 0 6px; text-align: center; }}
[class*="st-key-demo_"] button {{ border-radius: 999px !important; min-height: 38px !important; font-size: 13px !important;
  background: rgba(255,255,255,.06) !important; border: 1px solid rgba(253,230,138,.35) !important; color: #FDE68A !important;
  backdrop-filter: blur(10px); }}
.st-key-login_card [data-testid="stHorizontalBlock"] {{ flex-wrap: nowrap; align-items: center; gap: .5rem; }}
.st-key-login_card [data-testid="stColumn"] {{ width: auto !important; min-width: 0; flex: 1 1 0 !important; }}
.st-key-google_btn button p::before {{ content: ""; display: inline-block; width: 18px; height: 18px; margin-right: 10px;
  vertical-align: -3px; background: url("{GOOGLE_G}") no-repeat center / contain; }}
.lg-console {{ background: linear-gradient(135deg, rgba(37,99,235,.25), rgba(124,58,237,.25)); color: #F8FAFC;
  border: 1px solid rgba(255,255,255,.14); border-radius: 14px; padding: 14px 16px; margin-bottom: 16px; font-weight: 700;
  display: flex; gap: 12px; align-items: center; }}
.lg-console svg {{ width: 34px; height: 34px; border-radius: 9px; }}
.lg-console small {{ display: block; font-weight: 500; color: #CBD5E1; font-size: 13px; }}
@media (max-width: 768px) {{
  .st-key-login_head {{ margin-top: 2vh; }} .lg-tag {{ font-size: 19px; }} .lg-feats {{ display: none; }}
  .st-key-login_card {{ padding: 22px 18px 16px; border-radius: 18px; backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px); }}
}}
@media (prefers-reduced-motion: reduce) {{ .lg-bg path, .st-key-login_card, .lg-mark svg {{ animation: none; }} }}
</style><div class="lg-bg">{ROUTES_SVG}</div>""", unsafe_allow_html=True)


def brand_header():
    feats = "".join(f"<span>{ui.icon(name)}{escape(text)}</span>" for name, text in FEATURES)
    with st.container(key="login_head"):
        st.markdown(f"""<div class="lg-mark">{ui.MARK_SVG}<span>{ui.APP_NAME}</span></div>
<p class="lg-tag">{escape(ui.TAGLINE)}</p><p class="lg-sub">Disruption-Aware Logistics Decision Support</p>
<div class="lg-feats">{feats}</div>""", unsafe_allow_html=True)


def footer():
    st.markdown(f"<div class='lg-foot'>HackNext'26 · {escape(ui.TEAM_NAME)}</div>", unsafe_allow_html=True)


GOOGLE_G = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'>"
            "<path fill='%23FFC107' d='M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 "
            "12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3"
            "-.1-2.4-.4-3.5z'/><path fill='%23FF3D00' d='M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 "
            "3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z'/><path fill='%234CAF50' d='M24 44c5.2 0 9.9-2 "
            "13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z'/>"
            "<path fill='%231976D2' d='M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24"
            "c0-1.3-.1-2.4-.4-3.5z'/></svg>")
