"""'Report a problem' flow shared by the partner app and the manager's 'Log an issue'.

1. tap a quick type, record a voice note, or type     2. "Check" -> what we understood
3. fix the place if needed                              4. "Send" -> manager gets problem + AI plan
"""
from html import escape

import streamlit as st

from modules import issues, store, ui
from modules.voice import available_engines


def _key(prefix, name):
    """Widget keys include a counter so the form can be cleared after sending."""
    return f"{prefix}_{name}_{st.session_state.get(f'{prefix}_round', 0)}"


def _clear(prefix):
    st.session_state[f"{prefix}_round"] = st.session_state.get(f"{prefix}_round", 0) + 1
    st.session_state.pop(f"{prefix}_preview", None)
    ui.resume_live_updates()


def report_form(partner_id, prefix="report", source="partner"):
    """Draw the form. Returns the new issue id right after sending, else None."""
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
            result = issues.preview(partner_id, text=text, audio=audio_bytes, quick_type=quick)
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
            data = store.snapshot()
            own = issues.route_roads(issues.reporter(partner_id), data)
            names = dict(zip(data["roads"]["road_id"], data["roads"]["name"]))
            options = [r for r, _ in own] + [r for r in names if r not in dict(own)]
            st.markdown("**Where is it?** Tap the road:")
            road = st.pills("Road", options, format_func=names.get, key=_key(prefix, "road"),
                            label_visibility="collapsed")
            if road:
                problem = issues.set_location(problem, road, data)
                preview["problem"] = problem
        st.markdown(f"**{problem['summary']}**")
        if problem.get("suggestions") and not problem.get("needs_location"):
            st.caption("Also possible: " + ", ".join(problem["suggestions"]))

        send, again = st.columns(2)
        if send.button("Send to manager", type="primary", width="stretch", icon=":material/send:",
                       key=_key(prefix, "send"), disabled=problem.get("needs_location", False)):
            issue_id = issues.submit(partner_id, problem, transcript=preview["transcript"],
                                     engine=preview["engine"], audio=preview["audio"], quick_type=preview["quick"],
                                     source=source)
            _clear(prefix)
            return issue_id
        if again.button("Start again", width="stretch", key=_key(prefix, "again")):
            _clear(prefix)
            st.rerun()
    return None
