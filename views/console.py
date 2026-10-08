"""Admin console sign-in – Super Admins only, at the unlisted URL /console (never linked from the
public sign-in page). Super Admins cannot sign in anywhere else; nobody else can sign in here."""
import streamlit as st

from modules import auth, login_ui as lui, ui

lui.page_css()
st.markdown("<div style='height:10vh'></div>", unsafe_allow_html=True)
with st.container(key="login_card"):
    st.markdown(f"<div class='lg-console'>{ui.MARK_SVG}<div>Admin console<small>Super Admins only</small></div></div>",
                unsafe_allow_html=True)
    message = st.session_state.pop("console_msg", None)
    if message:
        (st.warning if message == auth.MESSAGES["locked"] else st.error)(message, icon=":material/error:")
    with st.form("console_form", border=False, enter_to_submit=True):
        identifier = st.text_input("Email", placeholder="you@deport.in", key="sa_id", autocomplete="username")
        password = st.text_input("Password", type="password", key="sa_pw", autocomplete="current-password")
        submitted = st.form_submit_button("Sign in", type="primary", width="stretch", icon=":material/lock_open:")
    if submitted:
        with st.spinner("Signing in…"):
            user, error = auth.authenticate(identifier, password, portal="super")
        if user:
            lui.finish(user)
        st.session_state["console_msg"] = error
        st.rerun()
