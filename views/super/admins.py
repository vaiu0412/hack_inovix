"""Admins: one per branch – switch on/off, reset password, add an admin."""
from html import escape

import streamlit as st

from modules import admin, guards, store, ui

actor = guards.require_permission("manage_branch_admins")
ui.header("Admins", "Temporary passwords show once.")

admins = admin.branch_admins_df()
for a in admins.to_dict("records"):
    with ui.card(f"admin_{a['user_id']}"):
        info, toggle = st.columns([5, 1.2], vertical_alignment="center")
        status = ui.pill_html("normal", "Active") if a["is_active"] else ui.pill_html("off", "Off")
        info.markdown(f"<p class='dp-h3'>{escape(a['display_name'])} &nbsp;{status}</p><p class='dp-small'>"
                      f"{escape(a['email'])} · {escape(str(a['branch'] or a['branch_id']))} · last sign-in "
                      f"{a['last_login'] or '—'}</p>", unsafe_allow_html=True)
        active = toggle.toggle("Active", value=bool(a["is_active"]), key=f"admin_active_{a['user_id']}")
        if active != bool(a["is_active"]):
            admin.set_user_active(actor, a["user_id"], active)
            st.toast(f"{a['display_name']} {'on' if active else 'off'}.")
            st.rerun()

with st.expander("Reset password", icon=":material/key:"):
    target = st.selectbox("Admin", admins["user_id"].tolist(), format_func=lambda uid: admins.set_index(
        "user_id").loc[uid, "display_name"] + f" · {uid}")
    if st.button("Reset password", key="reset_admin_pw", type="primary"):
        temp = admin.generate_temp_password()
        admin.reset_admin_password(actor, target, temp)
        st.success("Done. Share it once:")
        st.code(temp, language=None)

ui.section("Add admin", "person_add")
branches = store.branches_df()
with ui.card("add_admin"):
    if st.button("Generate password", icon=":material/password:", key="gen_pw"):
        st.session_state["new_admin_pw"] = admin.generate_temp_password()
    with st.form("create_admin", clear_on_submit=True, border=False):
        c1, c2 = st.columns(2)
        name = c1.text_input("Name")
        email = c2.text_input("Email", placeholder="west.admin@deport.in")
        c3, c4 = st.columns(2)
        phone = c3.text_input("Phone", placeholder="+91 90000 10004")
        branch = c4.selectbox("Branch", branches["branch_id"].tolist(),
                              format_func=lambda b: branches.set_index("branch_id").loc[b, "name"])
        temp = st.text_input("Temp password", value=st.session_state.get("new_admin_pw", ""),
                             help="8+ characters, a letter and a number")
        if st.form_submit_button("Add admin", type="primary", icon=":material/person_add:"):
            try:
                admin.create_branch_admin(actor, name, email, phone, branch, temp)
                st.session_state.pop("new_admin_pw", None)
                st.success(f"{name} added. Sign-in: {email}")
            except (ValueError, PermissionError) as error:
                st.error(str(error))
