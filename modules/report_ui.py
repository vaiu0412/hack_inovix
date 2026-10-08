"""'Report a problem' flow shared by the partner app and the manager's 'Log an issue'.

1. tap a quick type, record a voice note, or type     2. "Check" -> what we understood
3. fix the place if needed                              4. "Send" -> manager gets problem + AI plan

Partners go through modules/partner_scope (only their own data, reports always filed as
themselves); the manager's 'Log an issue' uses the operations-wide functions.
"""
from html import escape

import streamlit as st

from modules import issues, ui
from modules.data_loader import load_all
from modules.voice import available_engines


def _backend(reporter_id, source):
    """(preview, submit, road options) for this kind of reporter."""
    if source == "partner":
        from modules import partner_scope as scope

        return (lambda **kw: scope.preview_issue(reporter_id, **kw),
                lambda problem, **kw: scope.report_issue(reporter_id, problem, **kw),
                lambda: scope.route_road_options(reporter_id))
    roads = load_all()["roads"]
    return (lambda **kw: issues.preview(reporter_id, **kw),
            lambda problem, **kw: issues.submit(reporter_id, problem, source="manager", **kw),
            lambda: list(zip(roads["road_id"], roads["name"])))


def _key(prefix, name):
    """Widget keys include a counter so the form can be cleared after sending."""
    return f"{prefix}_{name}_{st.session_state.get(f'{prefix}_round', 0)}"


def _clear(prefix):
    st.session_state[f"{prefix}_round"] = st.session_state.get(f"{prefix}_round", 0) + 1
    st.session_state.pop(f"{prefix}_preview", None)
    ui.resume_live_updates()


def report_form(partner_id, prefix="report", source="partner"):
    """Draw the form. Returns the new issue id right after sending, else None."""
    preview_fn, submit_fn, road_options_fn = _backend(partner_id, source)
    quick = st.pills("What happened?", list(issues.QUICK_TYPES), format_func=issues.QUICK_TYPES.get,
                     key=_key(prefix, "quick"))
    audio = st.audio_input("Voice note (Tamil, English or both)", key=_key(prefix, "audio"))
    text = st.text_area("Or type it", key=_key(prefix, "text"), height=80,
                        placeholder="e.g. Avinashi road la accident, rendu mani neram block")
    engines = available_engines()
    st.caption("Voice is understood by " + (engines[0] if engines else "no engine right now – please type")
               + ". Place names can be misspelled.")

    if st.button("Check", type="primary", width="stretch", key=_key(prefix, "check"),
                 icon=":material/fact_check:", disabled=not (audio or text.strip() or quick)):
        audio_bytes = audio.getvalue() if audio else None
        ui.pause_live_updates()  # keep the preview on screen until it is sent
        with st.spinner("Listening and understanding…"):
            result = preview_fn(text=text, audio=audio_bytes, quick_type=quick)
        st.session_state[f"{prefix}_preview"] = {**result, "audio": audio_bytes, "quick": quick}

    preview = st.session_state.get(f"{prefix}_preview")
    if not preview:
        return None
    if preview["engine"] == "not understood":
        st.warning("We couldn't make out the voice note. Type one line instead – the recording is kept.",
                   icon=":material/hearing_disabled:")
    problem = preview["problem"]
    if not problem:
        return None

    with st.container(border=True):
        st.markdown("**We understood**")
        if preview["transcript"]:
            st.markdown(f'<div class="rp-quote">“{escape(preview["transcript"])}”</div>', unsafe_allow_html=True)
        if problem.get("needs_location"):
            options = road_options_fn()  # own roads first for partners
            names = dict(options)
            st.markdown("**Where is it?** Tap the road:")
            road = st.pills("Road", [r for r, _ in options], format_func=names.get, key=_key(prefix, "road"),
                            label_visibility="collapsed")
            if road:
                problem = issues.set_location(problem, road, {"roads": load_all()["roads"]})
                preview["problem"] = problem
        st.markdown(f"**{problem['summary']}**")
        if problem.get("suggestions") and not problem.get("needs_location"):
            st.caption("Also possible: " + ", ".join(problem["suggestions"]))

        send, again = st.columns(2)
        if send.button("Send to manager", type="primary", width="stretch", icon=":material/send:",
                       key=_key(prefix, "send"), disabled=problem.get("needs_location", False)):
            issue_id = submit_fn(problem, transcript=preview["transcript"], engine=preview["engine"],
                                 audio=preview["audio"], quick_type=preview["quick"])
            _clear(prefix)
            return issue_id
        if again.button("Start again", width="stretch", key=_key(prefix, "again")):
            _clear(prefix)
            st.rerun()
    return None
