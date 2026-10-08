"""Sign-in page – the only public page. One card, three views: sign in · OTP · forgot password.
The role comes from the account, so everyone lands on their own dashboard. (Super Admins use the
separate console at /console; this page never links to it.)"""
import time

import streamlit as st

from modules import auth, guards, login_ui as lui

VIEWS = ("signin", "otp", "forgot")
PLACEHOLDER = "you@deport.in or DP102"


def go(view, **state):
    st.session_state["login_view"] = view
    for key, value in state.items():
        st.session_state[key] = value


def show(message, kind="error"):
    st.session_state["login_msg"] = (message, kind)


def public_error(error):
    """Super Admin accounts get the same answer as a wrong password here (the console is not advertised)."""
    return auth.MESSAGES["bad_credentials"] if error == auth.MESSAGES["use_super_portal"] else error


def demo_code(code, purpose):
    """No SMS provider configured: show the code on screen, clearly labelled DEMO."""
    if code:
        st.toast(f"DEMO · Your DEPORT {purpose} code is {code}", icon=":material/sms:")


lui.page_css()
if st.query_params.get("view") in VIEWS:  # plain links (e.g. "Forgot password?") switch the card view
    go(st.query_params.get("view"))
    st.query_params.clear()
view = st.session_state.setdefault("login_view", "signin")

# real Google sign-in came back: the Google email must belong to an existing, active account
google_email = lui.google_email() if lui.google_configured() else None
google_error = None
if google_email and not st.session_state.get("authenticated"):
    user, google_error = lui.handle_google(google_email)
    if user:
        lui.finish(user)

lui.brand_header()
with st.container(key="login_page"):
    with st.container(key="login_card"):
        message = st.session_state.pop("login_msg", None)

        def flash():
            if message:
                text, kind = message
                {"error": st.error, "warning": st.warning, "success": st.success}[kind](
                    text, icon={"error": ":material/error:", "warning": ":material/timer:",
                                "success": ":material/check_circle:"}[kind])

        # ------------------------------------------------ sign in
        if view == "signin":
            st.markdown("<p class='lg-title'>Welcome back</p><p class='lg-sub2'>Sign in to DEPORT</p>",
                        unsafe_allow_html=True)
            flash()
            if google_error:  # signed in to Google, but no DEPORT account uses that email
                st.error(google_error, icon=":material/no_accounts:")
                if st.button("Use another account", icon=":material/logout:", key="google_logout", width="stretch"):
                    st.logout()
            with st.form("signin_form", border=False, enter_to_submit=True):
                identifier = st.text_input("Email or ID", placeholder=PLACEHOLDER, key="si_id", autocomplete="username")
                password = st.text_input("Password", type="password", key="si_pw", autocomplete="current-password")
                left, right = st.columns(2, vertical_alignment="center")
                remember = left.checkbox("Remember me", value=True, key="si_remember")
                right.markdown("<div class='lg-link'><a href='?view=forgot' target='_self'>Forgot password?</a></div>",
                               unsafe_allow_html=True)
                submitted = st.form_submit_button("Sign in", type="primary", width="stretch")
            if submitted:
                with st.spinner("Signing in…"):
                    user, error = auth.authenticate(identifier, password)
                if user:
                    lui.finish(user, remember)
                error = public_error(error)
                show(error, "warning" if error == auth.MESSAGES["locked"] else "error")
                st.rerun()
            st.markdown("<div class='lg-or'>or</div>", unsafe_allow_html=True)
            if lui.google_configured():  # real Google OIDC only; no button at all when it isn't set up
                if st.button("Continue with Google", key="google_btn", width="stretch"):
                    st.login("google")
            if st.button("Sign in with OTP", icon=":material/mail:", key="otp_btn", width="stretch"):
                go("otp", otp_step=1)
                st.rerun()
            if lui.demo_mode():
                lui.demo_chips(["branch_admin", "partner"])

        # ------------------------------------------------ OTP sign-in
        elif view == "otp":
            st.markdown("<p class='lg-title'>Sign in with OTP</p><p class='lg-sub2'>Code to your email</p>",
                        unsafe_allow_html=True)
            flash()
            if st.session_state.get("otp_step", 1) == 1:
                with st.form("otp_send", border=False):
                    ident = st.text_input("Email or ID", placeholder=PLACEHOLDER, key="otp_id")
                    send = st.form_submit_button("Send code", type="primary", width="stretch")
                if send:
                    code, text, ok = auth.request_otp(ident, "login")
                    if ok:
                        st.session_state.update(otp_step=2, otp_ident=ident, otp_sent=time.time(), otp_demo=code)
                        demo_code(code, "sign-in")
                        show(text, "success")
                    else:
                        show(public_error(text))
                    st.rerun()
            else:
                if st.session_state.get("otp_demo"):
                    st.info(f"**DEMO** · code **{st.session_state['otp_demo']}** (no SMS set up)", icon=":material/sms:")
                with st.form("otp_verify", border=False):
                    code = st.text_input("6-digit code", max_chars=6, key="otp_code", placeholder="••••••")
                    verify = st.form_submit_button("Sign in", type="primary", width="stretch")
                if verify:
                    user, error = auth.verify_otp(st.session_state.get("otp_ident"), code, "login")
                    if user:
                        lui.finish(user)
                    show(error)
                    st.rerun()
                wait = guards.resend_wait("otp_sent")
                if st.button(f"Resend code{f' ({wait}s)' if wait else ''}", disabled=bool(wait), width="stretch",
                             key="otp_resend"):
                    code, text, ok = auth.request_otp(st.session_state.get("otp_ident"), "login")
                    st.session_state.update(otp_sent=time.time(), otp_demo=code)
                    demo_code(code, "sign-in")
                    show(text, "success" if ok else "error")
                    st.rerun()
            if st.button("Back to sign in", icon=":material/arrow_back:", type="tertiary", key="otp_back"):
                go("signin", otp_step=1, otp_demo=None)
                st.rerun()

        # ------------------------------------------------ forgot password
        elif view == "forgot":
            st.markdown("<p class='lg-title'>Reset password</p><p class='lg-sub2'>Code to your email</p>",
                        unsafe_allow_html=True)
            flash()
            if st.session_state.get("reset_step", 1) == 1:
                with st.form("reset_send", border=False):
                    ident = st.text_input("Email or ID", placeholder=PLACEHOLDER, key="reset_id")
                    send = st.form_submit_button("Send code", type="primary", width="stretch")
                if send:
                    code, text, ok = auth.request_otp(ident, "reset")
                    if ok:
                        st.session_state.update(reset_step=2, reset_ident=ident, reset_sent=time.time(), reset_demo=code)
                        demo_code(code, "reset")
                        show(text, "success")
                    else:
                        show(public_error(text))
                    st.rerun()
            else:
                if st.session_state.get("reset_demo"):
                    st.info(f"**DEMO** · code **{st.session_state['reset_demo']}** (no SMS set up)",
                            icon=":material/sms:")
                with st.form("reset_new", border=False):
                    code = st.text_input("6-digit code", max_chars=6, key="reset_code")
                    new = st.text_input("New password", type="password", key="reset_pw", help="8+ characters, a letter and a number")
                    confirm = st.text_input("Repeat password", type="password", key="reset_pw2")
                    save = st.form_submit_button("Save password", type="primary", width="stretch")
                if save:
                    if new != confirm:
                        show("Passwords don't match.")
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
