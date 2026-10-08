"""Branch Admins: list, create, activate / deactivate, reset password."""
from html import escape

import streamlit as st

from modules import admin, guards, store, ui

actor = guards.require_permission("manage_branch_admins")
ui.header("Branch Admins", "Each branch is run by its branch admin. Temporary passwords are shown once.")

admins = admin.branch_admins_df()
for a in admins.to_dict("records"):
    with st.container(border=True):
        info, toggle = st.columns([5, 1.2], vertical_alignment="center")
        status = ui.badge("Active", "rp-low") if a["is_active"] else ui.badge("Deactivated", "rp-neutral")
        info.markdown(f"**{escape(a['display_name'])}** &nbsp;{status}<br><small>{escape(a['email'])} · "
                      f"{escape(str(a['branch'] or a['branch_id']))} · last login {a['last_login'] or '—'}</small>",
                      unsafe_allow_html=True)
        active = toggle.toggle("Active", value=bool(a["is_active"]), key=f"admin_active_{a['user_id']}")
        if active != bool(a["is_active"]):
            admin.set_user_active(actor, a["user_id"], active)
            st.toast(f"{a['display_name']} {'activated' if active else 'deactivated'}")
            st.rerun()

with st.expander("Reset a branch admin's password", icon=":material/key:"):
    target = st.selectbox("Branch admin", admins["user_id"].tolist(), format_func=lambda uid: admins.set_index(
        "user_id").loc[uid, "display_name"] + f" · {uid}")
    if st.button("Generate and set temporary password", key="reset_admin_pw"):
        temp = admin.generate_temp_password()
        admin.reset_admin_password(actor, target, temp)
        st.success("Password reset. Share this temporary password once – it is not stored anywhere:")
        st.code(temp, language=None)

st.markdown("##### Create branch admin")
branches = store.branches_df()
if st.button("Generate temporary password", icon=":material/password:", key="gen_pw"):
    st.session_state["new_admin_pw"] = admin.generate_temp_password()
with st.form("create_admin", clear_on_submit=True):
    c1, c2 = st.columns(2)
    name = c1.text_input("Full name")
    email = c2.text_input("Email", placeholder="west.admin@deport.in")
    c3, c4 = st.columns(2)
    phone = c3.text_input("Phone", placeholder="+91 90000 10004")
    branch = c4.selectbox("Branch", branches["branch_id"].tolist(),
                          format_func=lambda b: branches.set_index("branch_id").loc[b, "name"])
    temp = st.text_input("Temporary password", value=st.session_state.get("new_admin_pw", ""),
                         help="At least 8 characters with a letter and a number")
    if st.form_submit_button("Create branch admin", type="primary", icon=":material/person_add:"):
        try:
            user_id = admin.create_branch_admin(actor, name, email, phone, branch, temp)
            st.session_state.pop("new_admin_pw", None)
            st.success(f"**{name}** can now sign in with **{email}** and the temporary password.")
        except (ValueError, PermissionError) as error:
            st.error(str(error))
