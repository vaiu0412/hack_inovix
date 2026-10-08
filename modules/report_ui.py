"""'Report' flow shared by the partner app and the branch admin's 'Log issue'.

1. tap one of 9 big tiles, record a voice note, or type     2. Check -> "We understood:"
3. pick the road if no place was found                       4. Send -> the branch admin gets an alert + AI plan

Partners go through modules/partner_scope (only their own data, reports always filed as
themselves); the branch admin's 'Log issue' uses the branch-scoped functions.
"""
from html import escape

import streamlit as st

from modules import issues, ui
from modules.data_loader import load_all
from modules.voice import available_engines

# (tile key, label, icon, quick type sent to the parser)
TILES = [
    ("accident", "Accident", ":material/car_crash:", "accident"),
    ("traffic", "Traffic", ":material/traffic:", "traffic"),
    ("closure", "Road blocked", ":material/block:", "closure"),
    ("flood", "Flooding", ":material/flood:", "flood"),
    ("breakdown", "Breakdown", ":material/car_repair:", "breakdown"),
    ("puncture", "Flat tyre", ":material/tire_repair:", "breakdown"),
    ("protest", "Protest", ":material/campaign:", "protest"),
    ("customer", "Customer away", ":material/person_off:", "customer_unavailable"),
    ("other", "Other", ":material/more_horiz:", "unknown"),
]
QUICK_OF = {key: quick for key, _, _, quick in TILES}


def _backend(reporter_id, source, branch_id):
    """(preview, submit, road options) for this kind of reporter, always inside one branch."""
    if source == "partner":
        from modules import partner_scope as scope

        return (lambda **kw: scope.preview_issue(reporter_id, branch_id, **kw),
                lambda problem, **kw: scope.report_issue(reporter_id, branch_id, problem, **kw),
                lambda: scope.route_road_options(reporter_id, branch_id))
    roads = load_all()["roads"]
    return (lambda **kw: issues.preview(reporter_id, branch_id=branch_id, **kw),
            lambda problem, **kw: issues.submit(reporter_id, problem, source="manager", branch_id=branch_id, **kw),
            lambda: list(zip(roads["road_id"], roads["name"])))


def _round(prefix):
    return st.session_state.get(f"{prefix}_round", 0)


def _key(prefix, name):
    """Widget keys include a counter so the form can be cleared after sending."""
    return f"{prefix}_{name}_{_round(prefix)}"


def _clear(prefix):
    st.session_state[f"{prefix}_round"] = _round(prefix) + 1
    st.session_state.pop(f"{prefix}_preview", None)
    ui.resume_live_updates()


def report_form(partner_id, branch_id, prefix="report", source="partner"):
    """Draw the form. Returns the new issue id right after sending, else None."""
    preview_fn, submit_fn, road_options_fn = _backend(partner_id, source, branch_id)
    picked_key = _key(prefix, "tile")
    picked = st.session_state.get(picked_key)

    st.markdown("<p class='dp-h3' style='margin-bottom:8px'>What happened?</p>", unsafe_allow_html=True)
    with st.container(horizontal=True, gap="small"):
        for key, label, icon, _ in TILES:
            if st.button(label, icon=icon, key=f"tile_{prefix}_{key}_{_round(prefix)}", width=92,
                         type="primary" if picked == key else "secondary"):
                st.session_state[picked_key] = None if picked == key else key
                st.rerun()
    quick = QUICK_OF.get(picked)
    audio = st.audio_input("Record voice", key=_key(prefix, "audio"))
    text = st.text_area("Or type", key=_key(prefix, "text"), height=80,
                        placeholder="Avinashi road la accident, rendu mani neram block")
    engines = available_engines()
    st.caption(f"Tamil, English or both · {engines[0] if engines else 'type one line'}")

    # always clickable: a typed line is committed when the field loses focus, so no Ctrl+Enter is needed
    if st.button("Check", type="primary", width="stretch", key=_key(prefix, "check"), icon=":material/fact_check:"):
        if not (audio or text.strip() or quick):
            st.warning("Tap a type, record or type.", icon=":material/info:")
            return None
        audio_bytes = audio.getvalue() if audio else None
        ui.pause_live_updates()  # keep the preview on screen until it is sent
        with st.spinner("Listening…"):
            result = preview_fn(text=text, audio=audio_bytes, quick_type=quick)
        st.session_state[f"{prefix}_preview"] = {**result, "audio": audio_bytes, "quick": quick}

    preview = st.session_state.get(f"{prefix}_preview")
    if not preview:
        return None
    if preview["engine"] == "not understood":
        st.warning("Voice not clear. Type one line.", icon=":material/hearing_disabled:")
    problem = preview["problem"]
    if not problem:
        return None

    with ui.card(f"understood_{prefix}"):
        st.markdown("<p class='dp-h3'>We understood:</p>", unsafe_allow_html=True)
        if preview["transcript"]:
            st.markdown(f'<div class="dp-quote">“{escape(preview["transcript"])}”</div>', unsafe_allow_html=True)
        if problem.get("needs_location"):
            options = road_options_fn()  # own roads first for partners
            names = dict(options)
            road = st.pills("Where?", [r for r, _ in options], format_func=names.get, key=_key(prefix, "road"))
            if road:
                problem = issues.set_location(problem, road, {"roads": load_all()["roads"]})
                preview["problem"] = problem
        st.markdown(f"<p style='font-size:16px;font-weight:650;margin:4px 0 12px'>{escape(problem['summary'])}</p>",
                    unsafe_allow_html=True)
        send, again = st.columns(2)
        if send.button("Send", type="primary", width="stretch", icon=":material/send:", key=_key(prefix, "send"),
                       disabled=problem.get("needs_location", False)):
            issue_id = submit_fn(problem, transcript=preview["transcript"], engine=preview["engine"],
                                 audio=preview["audio"], quick_type=preview["quick"])
            _clear(prefix)
            return issue_id
        if again.button("Start again", width="stretch", key=_key(prefix, "again")):
            _clear(prefix)
            st.rerun()
    return None
