"""Sign-in page – the only page before login. One card, four views:
sign in · OTP login · forgot password · Super Admin console. The role comes from the account."""
import time
from html import escape

import streamlit as st

from modules import auth, guards, ui
from modules.parser import setting

DEMO_MODE = str(setting("DEMO_MODE", "1")) != "0"
VIEWS = ("signin", "otp", "forgot", "super")

LOGO = """<svg width="38" height="38" viewBox="0 0 40 40" aria-hidden="true"><rect width="40" height="40" rx="11"
fill="#fff" fill-opacity=".14"/><path d="M7 21c3.5 0 3.5-4 7-4s3.5 4 7 4 3.5-4 7-4 3.5 4 5 4" stroke="#fff"
stroke-width="2.6" fill="none" stroke-linecap="round"/><path d="M7 28c3.5 0 3.5-4 7-4s3.5 4 7 4 3.5-4 7-4 3.5 4 5 4"
stroke="#93C5FD" stroke-width="2.6" fill="none" stroke-linecap="round"/><circle cx="20" cy="11" r="3"
fill="#93C5FD"/></svg>"""
ICONS = {
    "mic": '<path d="M12 3a3 3 0 0 0-3 3v6a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3"/>',
    "spark": '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z"/>',
    "bolt": '<path d="M13 2L4 14h7l-1 8 9-12h-7z"/>',
}
ROUTES_SVG = """<svg class="rp-routes" viewBox="0 0 600 800" preserveAspectRatio="none" aria-hidden="true">
<path d="M-20 620 C120 560 160 470 260 450 S420 380 470 260 560 120 640 80"/>
<path d="M-20 300 C80 330 140 260 230 280 S380 360 450 330 600 250 640 270"/>
<path d="M100 820 C130 700 210 650 260 560 S330 420 420 400 540 420 640 360"/>
<circle cx="260" cy="450" r="5"/><circle cx="450" cy="330" r="5"/><circle cx="420" cy="400" r="5"/></svg>"""
GOOGLE_G = ("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 48 48'>"
            "<path fill='%23FFC107' d='M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 "
            "12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3"
            "-.1-2.4-.4-3.5z'/><path fill='%23FF3D00' d='M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 "
            "3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z'/><path fill='%234CAF50' d='M24 44c5.2 0 9.9-2 "
            "13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z'/>"
            "<path fill='%231976D2' d='M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24"
            "c0-1.3-.1-2.4-.4-3.5z'/></svg>")


def icon(name):
    return (f'<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" '
            f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{ICONS[name]}</svg>')


def google_configured():
    try:
        return "auth" in st.secrets and ("google" in st.secrets["auth"] or "client_id" in st.secrets["auth"])
    except Exception:
        return False


def go(view, **state):
    st.session_state["login_view"] = view
    st.session_state.update(state)


def show(message, kind="error"):
    st.session_state["login_msg"] = (message, kind)


def finish(user, remember=False):
    guards.sign_in(user, remember=remember)
    st.rerun()


# ---------------------------------------------------------------- page chrome
dark = ui.is_dark()
card_bg, card_border, muted = ("#161B22", "#2A313B", "#9CA3AF") if dark else ("#FFFFFF", "#E5E7EB", "#6B7280")
st.markdown(f"""<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], header[data-testid="stHeader"],
[data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer {{ display: none !important; }}
.block-container {{ max-width: 100% !important; padding: 1rem 1.25rem !important; }}
.st-key-login_page [data-testid="stHorizontalBlock"] {{ min-height: calc(100vh - 2rem); }}
.rp-brand {{ position: relative; overflow: hidden; border-radius: 22px; min-height: calc(100vh - 2rem);
  background: linear-gradient(150deg, #0B1E3F 0%, #12306B 45%, #1D4ED8 100%); color: #fff;
  padding: 48px 52px; display: flex; flex-direction: column; justify-content: space-between; }}
.rp-routes {{ position: absolute; inset: 0; width: 100%; height: 100%; opacity: .16; }}
.rp-routes path {{ fill: none; stroke: #93C5FD; stroke-width: 2; stroke-dasharray: 7 9; }}
.rp-routes circle {{ fill: #93C5FD; }}
.rp-ripple {{ position: absolute; right: -120px; bottom: -120px; width: 520px; height: 520px; }}
.rp-ripple span {{ position: absolute; inset: 0; border-radius: 50%; border: 2px solid rgba(147,197,253,.35);
  animation: rp-wave 6s ease-out infinite; opacity: 0; }}
.rp-ripple span:nth-child(2) {{ animation-delay: 2s; }} .rp-ripple span:nth-child(3) {{ animation-delay: 4s; }}
@keyframes rp-wave {{ 0% {{ transform: scale(.25); opacity: .55; }} 100% {{ transform: scale(1.15); opacity: 0; }} }}
.rp-brand > :not(.rp-routes):not(.rp-ripple) {{ position: relative; }}
.rp-mark {{ display: flex; align-items: center; gap: 12px; font-weight: 800; letter-spacing: .18em; font-size: 1.15rem; }}
.rp-hero h1 {{ color: #fff; font-size: 2.5rem; line-height: 1.12; font-weight: 750; letter-spacing: -.02em;
  margin: 0 0 14px; padding: 0; max-width: 520px; }}
.rp-hero p {{ color: #DBEAFE; font-size: 1.12rem; margin: 0; }}
.rp-feats {{ list-style: none; padding: 0; margin: 34px 0 0; }}
.rp-feats li {{ display: flex; align-items: center; gap: 12px; margin-bottom: 14px; font-size: 1rem; color: #EFF6FF; }}
.rp-feats li span {{ width: 36px; height: 36px; border-radius: 10px; background: rgba(255,255,255,.12);
  display: inline-flex; align-items: center; justify-content: center; }}
.rp-foot {{ color: #BFDBFE; font-size: .85rem; opacity: .85; }}
.st-key-login_card {{ background: {card_bg}; border: 1px solid {card_border}; border-radius: 20px; max-width: 440px;
  width: 100%; margin: 0 auto; padding: 34px 32px 26px; box-shadow: 0 24px 48px rgba(15,23,42,.10),
  0 2px 6px rgba(15,23,42,.06); animation: rp-in .3s ease-out both; }}
@keyframes rp-in {{ from {{ opacity: 0; transform: translateY(14px); }} to {{ opacity: 1; transform: none; }} }}
.st-key-login_card p.rp-title {{ font-size: 1.7rem; font-weight: 750; letter-spacing: -.01em; margin: 0; line-height: 1.2; }}
.st-key-login_card p.rp-sub {{ color: {muted}; margin: 6px 0 18px; }}
.st-key-login_card button {{ min-height: 48px; font-weight: 600; border-radius: 12px; }}
.st-key-login_card input {{ min-height: 46px; }}
.st-key-login_card button:focus-visible, .st-key-login_card input:focus-visible {{ outline: 3px solid #93C5FD; }}
.rp-or {{ display: flex; align-items: center; gap: 12px; color: {muted}; font-size: .85rem; margin: 6px 0 10px; }}
.rp-or::before, .rp-or::after {{ content: ""; flex: 1; height: 1px; background: {card_border}; }}
.rp-link a {{ color: #2563EB; text-decoration: none; font-weight: 600; font-size: .92rem; }}
.rp-link {{ text-align: right; margin-top: 8px; }}
.rp-center {{ text-align: center; margin-top: 12px; font-size: .88rem; }}
.st-key-google_btn button {{ background: #fff !important; color: #1F2937 !important; border: 1px solid #D1D5DB !important; }}
.st-key-google_btn button p::before {{ content: ""; display: inline-block; width: 18px; height: 18px; margin-right: 10px;
  vertical-align: -3px; background: url("{GOOGLE_G}") no-repeat center / contain; }}
.rp-super-head {{ background: #0F172A; color: #F8FAFC; border-radius: 14px; padding: 14px 16px; margin-bottom: 16px;
  font-weight: 700; display: flex; gap: 10px; align-items: center; }}
.rp-super-head small {{ display: block; font-weight: 400; color: #94A3B8; }}
.rp-demo {{ font-size: .78rem; font-weight: 700; color: #B45309; background: #FEF3C7; border-radius: 999px;
  padding: 2px 10px; display: inline-block; margin-bottom: 8px; }}
/* columns inside the card (Remember me | Forgot password) keep their natural height and stay side by side */
.st-key-login_page .st-key-login_card [data-testid="stHorizontalBlock"] {{ min-height: auto; flex-direction: row;
  flex-wrap: nowrap; align-items: center; gap: .5rem; }}
.st-key-login_page .st-key-login_card [data-testid="stColumn"] {{ width: auto !important; min-width: 0;
  flex: 1 1 0 !important; }}
@media (max-width: 768px) {{
  .st-key-login_page [data-testid="stHorizontalBlock"] {{ flex-direction: column; min-height: auto; gap: .75rem; }}
  .st-key-login_page [data-testid="stColumn"] {{ width: 100% !important; flex: 1 1 100% !important; }}
  .rp-brand {{ min-height: auto; padding: 18px 20px; border-radius: 16px; }}
  .rp-hero h1 {{ font-size: 1.15rem; margin: 10px 0 0; }} .rp-hero p, .rp-feats, .rp-foot, .rp-ripple {{ display: none; }}
  .block-container {{ padding: .75rem .9rem !important; }}
  .st-key-login_card {{ padding: 24px 18px 18px; border-radius: 18px; box-shadow: none; }}
}}
</style>""", unsafe_allow_html=True)

# links like ?view=forgot switch the card view (they are plain links, so they look like links)
if st.query_params.get("view") in VIEWS:
    go(st.query_params.get("view"))
    st.query_params.clear()
view = st.session_state.setdefault("login_view", "signin")

# real Google sign-in came back: map the Google email to an existing account
if google_configured():
    try:
        google_email = st.user.email if st.user.is_logged_in else None
    except Exception:
        google_email = None
    if google_email:
        user, error = auth.user_for_google_email(google_email)
        if user:
            finish(user)
        show(error)


@st.dialog("Continue with Google")
def demo_google_chooser():
    st.markdown("<span class='rp-demo'>Demo mode</span>", unsafe_allow_html=True)
    st.caption("Google sign-in isn't configured on this server, so pick one of the demo accounts. "
               "Only existing, active accounts can sign in.")
    for account in auth.demo_google_accounts():
        role = auth.ROLE_LABELS[account["role_id"]]
        if st.button(f"{account['display_name']}  ·  {account['email']}", key=f"g_{account['email']}",
                     help=f"{role}{' · ' + account['branch'] if account['branch'] else ''}", width="stretch"):
            user, error = auth.user_for_google_email(account["email"])
            if user:
                finish(user)
            st.error(error)


# ---------------------------------------------------------------- layout
with st.container(key="login_page"):
    brand_col, card_col = st.columns([1.1, 1], gap="large", vertical_alignment="center")
    with brand_col:
        st.markdown(f"""<div class="rp-brand">{ROUTES_SVG}<div class="rp-ripple"><span></span><span></span><span></span></div>
<div><div class="rp-mark">{LOGO}<span>DEPORT</span></div>
<div class="rp-hero" style="margin-top:56px"><h1>AI-Powered Disruption-Aware Logistics</h1>
<p>From Disruption to Decision in Under a Minute.</p>
<ul class="rp-feats"><li><span>{icon('mic')}</span>Voice issue reporting</li>
<li><span>{icon('spark')}</span>AI ripple analysis</li><li><span>{icon('bolt')}</span>One-click recovery</li></ul></div></div>
<div class="rp-foot">HackNext'26 · {escape(ui.TEAM_NAME)}</div></div>""", unsafe_allow_html=True)

    with card_col, st.container(key="login_card"):
        message = st.session_state.pop("login_msg", None)

        def flash():
            if message:
                text, kind = message
                {"error": st.error, "warning": st.warning, "success": st.success}[kind](text)

        # ------------------------------------------------ sign in
        if view == "signin":
            st.markdown("<p class='rp-title'>Welcome back</p><p class='rp-sub'>Sign in to your DEPORT</p>",
                        unsafe_allow_html=True)
            flash()
            with st.form("signin_form", border=False, enter_to_submit=True):
                identifier = st.text_input("Email or User ID", placeholder="you@deport.in or DP102", key="si_id",
                                           autocomplete="username")
                password = st.text_input("Password", type="password", key="si_pw", autocomplete="current-password")
                left, right = st.columns(2, vertical_alignment="center")
                remember = left.checkbox("Remember me", key="si_remember")
                right.markdown("<div class='rp-link'><a href='?view=forgot' target='_self'>Forgot password?</a></div>",
                               unsafe_allow_html=True)
                submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
            if submitted:
                with st.spinner("Signing in…"):
                    user, error = auth.authenticate(identifier, password)
                if user:
                    finish(user, remember)
                show(error, "warning" if "Too many" in error else "error")
                st.rerun()
            st.markdown("<div class='rp-or'>or</div>", unsafe_allow_html=True)
            if (google_configured() or DEMO_MODE) and st.button("Continue with Google", key="google_btn",
                                                                 width="stretch"):
                if google_configured():
                    st.login("google")
                else:
                    demo_google_chooser()
            if st.button("Login with OTP", icon=":material/sms:", key="otp_btn", width="stretch"):
                go("otp", otp_step=1)
                st.rerun()
            st.markdown("<div class='rp-center rp-link' style='text-align:center'><a href='?view=super' "
                        "target='_self'>Super Admin access</a></div>", unsafe_allow_html=True)

        # ------------------------------------------------ OTP login
        elif view == "otp":
            st.markdown("<p class='rp-title'>Login with OTP</p><p class='rp-sub'>We'll text a 6-digit code to the "
                        "phone on your account</p>", unsafe_allow_html=True)
            flash()
            if st.session_state.get("otp_step", 1) == 1:
                with st.form("otp_send", border=False):
                    ident = st.text_input("Email or User ID", placeholder="you@deport.in or DP102", key="otp_id")
                    send = st.form_submit_button("Send code", type="primary", width="stretch")
                if send:
                    code, text, ok = auth.request_otp(ident, "login")
                    if ok:
                        st.session_state.update(otp_step=2, otp_ident=ident, otp_sent=time.time(), otp_demo=code)
                        if code:
                            st.toast(f"📱 Demo SMS: Your DEPORT login code is {code}")
                        show(text, "success")
                    else:
                        show(text)
                    st.rerun()
            else:
                if st.session_state.get("otp_demo"):
                    st.info(f"📱 **Demo SMS** – your code is **{st.session_state['otp_demo']}**", icon=":material/sms:")
                with st.form("otp_verify", border=False):
                    code = st.text_input("6-digit code", max_chars=6, key="otp_code", placeholder="••••••")
                    verify = st.form_submit_button("Verify and sign in", type="primary", width="stretch")
                if verify:
                    user, error = auth.verify_otp(st.session_state.get("otp_ident"), code, "login")
                    if user:
                        finish(user)
                    show(error)
                    st.rerun()
                wait = guards.resend_wait("otp_sent")
                if st.button(f"Resend code{f' in {wait} s' if wait else ''}", disabled=bool(wait), width="stretch",
                             key="otp_resend"):
                    code, text, ok = auth.request_otp(st.session_state.get("otp_ident"), "login")
                    st.session_state.update(otp_sent=time.time(), otp_demo=code)
                    if code:
                        st.toast(f"📱 Demo SMS: Your DEPORT login code is {code}")
                    show(text, "success" if ok else "error")
                    st.rerun()
            if st.button("Back to sign in", icon=":material/arrow_back:", type="tertiary", key="otp_back"):
                go("signin", otp_step=1, otp_demo=None)
                st.rerun()

        # ------------------------------------------------ forgot password
        elif view == "forgot":
            st.markdown("<p class='rp-title'>Reset your password</p><p class='rp-sub'>We'll send a code to the phone on "
                        "your account</p>", unsafe_allow_html=True)
            flash()
            if st.session_state.get("reset_step", 1) == 1:
                with st.form("reset_send", border=False):
                    ident = st.text_input("Email or User ID", placeholder="you@deport.in or DP102", key="reset_id")
                    send = st.form_submit_button("Send reset code", type="primary", width="stretch")
                if send:
                    code, text, ok = auth.request_otp(ident, "reset")
                    if ok:
                        st.session_state.update(reset_step=2, reset_ident=ident, reset_sent=time.time(), reset_demo=code)
                        if code:
                            st.toast(f"📱 Demo SMS: Your DEPORT reset code is {code}")
                        show(text, "success")
                    else:
                        show(text)
                    st.rerun()
            else:
                if st.session_state.get("reset_demo"):
                    st.info(f"📱 **Demo SMS** – your reset code is **{st.session_state['reset_demo']}**",
                            icon=":material/sms:")
                with st.form("reset_new", border=False):
                    code = st.text_input("6-digit code", max_chars=6, key="reset_code")
                    new = st.text_input("New password", type="password", key="reset_pw",
                                        help="At least 8 characters with a letter and a number")
                    confirm = st.text_input("Confirm new password", type="password", key="reset_pw2")
                    save = st.form_submit_button("Set new password", type="primary", width="stretch")
                if save:
                    if new != confirm:
                        show("The two passwords don't match.")
                    else:
                        ok, text = auth.reset_password_with_otp(st.session_state.get("reset_ident"), code, new)
                        if ok:
                            go("signin", reset_step=1, reset_demo=None)
                            show(text, "success")
                        else:
                            show(text)
                    st.rerun()
            if st.button("Back to sign in", icon=":material/arrow_back:", type="tertiary", key="reset_back"):
                go("signin", reset_step=1, reset_demo=None)
                st.rerun()

        # ------------------------------------------------ Super Admin console
        elif view == "super":
            st.markdown("<div class='rp-super-head'>🔒<div>Super Admin Console<small>Branches, branch admins and "
                        "audit log</small></div></div>", unsafe_allow_html=True)
            flash()
            with st.form("super_form", border=False, enter_to_submit=True):
                identifier = st.text_input("Super Admin email", placeholder="you@deport.in", key="sa_id",
                                           autocomplete="username")
                password = st.text_input("Password", type="password", key="sa_pw", autocomplete="current-password")
                submitted = st.form_submit_button("Sign in to console", type="primary", width="stretch")
            if submitted:
                with st.spinner("Signing in…"):
                    user, error = auth.authenticate(identifier, password, portal="super")
                if user:
                    finish(user)
                show(error, "warning" if "Too many" in error else "error")
                st.rerun()
            if st.button("Back to workspace sign in", icon=":material/arrow_back:", type="tertiary", key="sa_back"):
                go("signin")
                st.rerun()
