"""Home: brand panel + sign-in card. Nothing operational is queried or shown before login."""
import streamlit as st

from modules import auth, guards, ui

ROLE_LABELS = {"manager": "🧭 Manager", "partner": "🛵 Delivery Partner"}
ID_LABELS = {"manager": "Username", "partner": "Partner ID (e.g. DP102)"}

dark = ui.is_dark()
card_bg, card_border = ("#161B22", "#2A313B") if dark else ("#FFFFFF", "#E5E7EB")
st.markdown(f"""
<style>
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"], [data-testid="stSidebarNav"],
header[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"], #MainMenu, footer {{
  display: none !important; }}
.block-container {{ padding-top: 2.2rem !important; padding-bottom: 2rem; max-width: 1080px; }}
.st-key-home {{ min-height: calc(100vh - 5rem); justify-content: center; }}
.rp-brand-panel {{ background: linear-gradient(135deg, #1E3A8A 0%, #2563EB 100%); color: #fff; border-radius: 16px;
  padding: 44px 40px; min-height: 470px; display: flex; flex-direction: column; justify-content: space-between;
  box-shadow: 0 18px 40px rgba(30, 58, 138, .25); }}
.rp-brand-logo {{ font-size: 1.6rem; font-weight: 800; letter-spacing: .14em; }}
.rp-brand-title {{ font-size: 2.15rem; font-weight: 700; line-height: 1.15; margin: 26px 0 12px; letter-spacing: -.01em; }}
.rp-brand-tag {{ font-size: 1.08rem; opacity: .9; margin: 0; }}
.rp-brand-features {{ list-style: none; padding: 0; margin: 30px 0 0; }}
.rp-brand-features li {{ margin: 0 0 12px; font-size: 1.02rem; display: flex; gap: 10px; align-items: center; }}
.rp-brand-features span {{ width: 34px; height: 34px; border-radius: 10px; background: rgba(255, 255, 255, .14);
  display: inline-flex; align-items: center; justify-content: center; }}
.rp-brand-foot {{ opacity: .72; font-size: .85rem; margin-top: 30px; }}
.st-key-login_card {{ background: {card_bg}; border: 1px solid {card_border}; border-radius: 16px; max-width: 420px;
  margin: 0 auto; padding: 34px 30px 26px; box-shadow: 0 12px 32px rgba(15, 23, 42, .08), 0 1px 3px rgba(15, 23, 42, .06); }}
.rp-welcome {{ font-size: 1.75rem; font-weight: 700; margin: 0; letter-spacing: -.01em; line-height: 1.2; }}
.rp-welcome-sub {{ opacity: .65; margin: 4px 0 14px; }}
.st-key-login_card button {{ min-height: 48px; font-weight: 600; }}
.st-key-login_card input {{ min-height: 46px; }}
@media (max-width: 640px) {{
  .block-container {{ padding-left: .9rem; padding-right: .9rem; padding-top: 1rem !important; }}
  .st-key-home {{ min-height: auto; }}
  .st-key-home [data-testid="stHorizontalBlock"] {{ flex-direction: column-reverse; gap: 1rem; }}
  .rp-brand-panel {{ min-height: auto; padding: 24px 22px; }}
  .rp-brand-title {{ font-size: 1.45rem; margin: 14px 0 8px; }}
  .rp-brand-features {{ margin-top: 16px; }}
  .rp-brand-foot {{ margin-top: 14px; }}
  .st-key-login_card {{ padding: 24px 18px 18px; }}
}}
</style>""", unsafe_allow_html=True)

with st.container(key="home"):
    brand, login = st.columns([1.1, 1], gap="large", vertical_alignment="center")
    with brand:
        st.markdown(f"""
<div class="rp-brand-panel">
  <div>
    <div class="rp-brand-logo">🌊 RIPPLE</div>
    <div class="rp-brand-title">AI-Powered Disruption-Aware Logistics</div>
    <p class="rp-brand-tag">From Disruption to Decision in Under a Minute.</p>
    <ul class="rp-brand-features">
      <li><span>🎙️</span>Report issues by voice</li>
      <li><span>🧠</span>AI understands the ripple</li>
      <li><span>⚡</span>One-click recovery</li>
    </ul>
  </div>
  <div class="rp-brand-foot">HackNext'26 · {ui.TEAM_NAME}</div>
</div>""", unsafe_allow_html=True)

    with login, st.container(key="login_card"):
        st.markdown("<div class='rp-welcome'>Welcome back</div><div class='rp-welcome-sub'>Sign in to continue</div>",
                    unsafe_allow_html=True)
        role = st.segmented_control("I am a", list(ROLE_LABELS), format_func=ROLE_LABELS.get, key="login_role",
                                    width="stretch", label_visibility="collapsed")
        with st.form("login_form", border=False, enter_to_submit=True):
            user_id = st.text_input(ID_LABELS.get(role, "Username or Partner ID"), key="login_user",
                                    autocomplete="username")
            password = st.text_input("Password", type="password", key="login_password",
                                     autocomplete="current-password")
            submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
        if submitted:
            user, error = auth.login(role, user_id, password)
            if error:
                st.error(error, icon=":material/error:")
            else:
                guards.sign_in(user)
                st.rerun()
