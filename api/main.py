"""DEPORT REST API – the same logic, database and sessions as the Streamlit app, for a native mobile app.

Run:   uvicorn api.main:app --reload
Docs:  http://localhost:8000/docs   (click "Authorize" and paste the token from POST /login)

Auth:  POST /login {identifier, password, super_console?} -> {"token": ...} (a server-side session,
       only its hash is stored); send "Authorization: Bearer <token>"; POST /logout revokes it.
Roles: Super Admin   -> /branches (summaries), /demo/reset
       Branch Admin  -> /kpis, /partners, /deliveries, /map, /issues, /escalations – own branch only
       Delivery Partner -> /me… – own data only; dp_id and branch come from the session
Calls: /twilio/voice and /twilio/gather are Twilio webhooks (signed requests only), see docs/AI_CALL.md.
       A background task moves order offers along every 20 s (ESCALATION_SCHEDULER=off disables it);
       another retrains the acceptance model once a day when new decisions came in (LEARNING_SCHEDULER=off);
       another runs the live feeds every minute – weather, traffic, simulated movement (FEEDS_SCHEDULER=off).
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from modules import auth, escalation, issues, learning, operations, partner_scope, pod, realtime, store, tracking
from modules.data_loader import load_all
from modules.parser import setting
from services import voice_call

log = logging.getLogger("deport.api")
ESCALATION_EVERY_SEC = 20


async def _escalation_loop():
    """Move order offers along even when no Streamlit page is open."""
    while True:
        await asyncio.sleep(ESCALATION_EVERY_SEC)
        try:
            changes = await asyncio.to_thread(escalation.tick)
            if changes:
                log.info("escalation: %s", changes)
        except Exception:  # keep the loop alive; the next tick tries again
            log.exception("escalation tick failed")


async def _learning_loop():
    """Nightly retrain: checks every hour, trains when the model is a day old and new decisions came in."""
    while True:
        await asyncio.sleep(3600)
        try:
            result = await asyncio.to_thread(learning.maybe_retrain)
            if result.get("trained"):
                log.info("acceptance model retrained: %s", result)
        except Exception:
            log.exception("acceptance retrain failed")


async def _feeds_loop():
    """Weather (10 min), traffic (10 min, with a key) and simulated movement, even when no page is open."""
    while True:
        await asyncio.sleep(60)
        try:
            done = await asyncio.to_thread(realtime.poll)
            if done:
                log.info("live feeds: %s", list(done))
        except Exception:
            log.exception("live feeds failed")


@asynccontextmanager
async def lifespan(_app):
    """Create or upgrade the database when the API starts, and run the escalation timer."""
    store.init_db()
    tasks = []
    if str(setting("ESCALATION_SCHEDULER", "on")).lower() != "off":
        tasks.append(asyncio.create_task(_escalation_loop()))
    if str(setting("LEARNING_SCHEDULER", "on")).lower() != "off":
        tasks.append(asyncio.create_task(_learning_loop()))
    if str(setting("FEEDS_SCHEDULER", "on")).lower() != "off":
        tasks.append(asyncio.create_task(_feeds_loop()))
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="DEPORT API", version="4.0", lifespan=lifespan,
              description="Disruption-aware delivery operations with 3-level access: Super Admin, Branch Admin, "
                          "Delivery Partner.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- sessions
def _token(authorization):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in first: POST /login, then send 'Authorization: Bearer <token>'")
    return authorization.split(" ", 1)[1].strip()


def current_user(authorization: str | None = Header(None)):
    """The signed-in user from the 'Authorization: Bearer <token>' header, or 401."""
    user = auth.validate_session(_token(authorization))
    if user is None:
        raise HTTPException(401, "Invalid, expired or revoked session")
    return user


def super_only(user=Depends(current_user)):
    """Allow Super Admins only (403 otherwise)."""
    if user["role"] != "super_admin":
        raise HTTPException(403, "Super Admins only")
    return user


def branch_admin_only(user=Depends(current_user)):
    """Allow Branch Admins only (403 otherwise); their branch comes from the session."""
    if user["role"] != "branch_admin":
        raise HTTPException(403, "Branch Admins only")
    return user


def partner_only(user=Depends(current_user)):
    """Allow delivery partners only (403 otherwise); their DP id comes from the session."""
    if user["role"] != "partner" or not user.get("dp_id"):
        raise HTTPException(403, "Delivery partners only")
    return user


# ---------------------------------------------------------------- models + helpers
class LoginIn(BaseModel):
    """Sign-in form: email or DP id, password, and whether this is the Super Admin console."""
    identifier: str
    password: str
    super_console: bool = False
    remember_me: bool = False


class IssueIn(BaseModel):
    """A partner's typed report: free text, optional quick type and optional road picked by hand."""
    text: str = ""
    quick_type: str | None = None
    road_id: str | None = None  # when the reporter picked the road by hand


class AdminIssueIn(IssueIn):
    """An issue logged by a Branch Admin for one of their partners or the operations desk."""
    partner_id: str = "OPS"  # who is affected (a partner of the branch), or the operations desk


class IssueEdit(BaseModel):
    """Corrections a Branch Admin makes to what the AI understood."""
    type: str | None = None
    road_id: str | None = None
    severity: str | None = None
    duration_min: int | None = None


class DeclineIn(BaseModel):
    """Why the partner can't take an order."""

    reason: str = "Other"


class LocationIn(BaseModel):
    """A position from the partner's phone (GPS)."""

    lat: float
    lng: float
    accuracy_m: float | None = None


class Decision(BaseModel):
    """Why a Branch Admin rejected a plan."""
    reason: str = "Not needed"


def _clean(obj):
    """Plain JSON types only (pandas/numpy numbers become normal numbers)."""
    return json.loads(json.dumps(obj, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


def _public(issue):
    out = {k: v for k, v in issue.items() if k != "audio"}
    out["has_audio"] = bool(issue.get("audio"))
    return _clean(out)


def _records(df):
    return json.loads(df.to_json(orient="records"))


def _issue_or_404(issue_id, branch_id):
    issue = store.get_issue(issue_id, branch_id)
    if issue is None:
        raise HTTPException(404, f"No issue #{issue_id} in your branch")
    return issue


def _with_location(problem, road_id):
    return issues.set_location(problem, road_id, {"roads": load_all()["roads"]}) if road_id else problem


def _forbidden(call):
    try:
        return call()
    except PermissionError as error:
        raise HTTPException(403, str(error)) from error


# ---------------------------------------------------------------- public
@app.get("/health")
def health():
    """Liveness check for load balancers and uptime monitors."""
    return {"status": "ok"}


@app.post("/login")
def login(body: LoginIn):
    """Sign in and get a session token (403 wrong details, 429 locked)."""
    user, error = auth.authenticate(body.identifier, body.password, "super" if body.super_console else "workspace")
    if error:
        status = 429 if error == auth.MESSAGES["locked"] else 403 if error in (
            auth.MESSAGES["inactive"], auth.MESSAGES["branch_inactive"], auth.MESSAGES["use_super_portal"],
            auth.MESSAGES["super_only"]) else 401
        raise HTTPException(status, error)
    token = auth.create_session(user["user_id"], remember_me=body.remember_me)
    return {"token": token, "token_type": "bearer", "user": _clean(user)}


@app.post("/logout")
def logout(authorization: str | None = Header(None)):
    """Revoke the current session token."""
    auth.revoke_session(_token(authorization))
    return {"ok": True}


# ---------------------------------------------------------------- Super Admin (summary level)
@app.get("/branches")
def branches(_=Depends(super_only)):
    """All branches with summary counts (Super Admin)."""
    return _records(store.branch_summaries())


@app.post("/demo/reset")
def reset(_=Depends(super_only)):
    """Reset the demo data after saving a backup (Super Admin)."""
    store.reset_demo()
    return {"ok": True}


# ---------------------------------------------------------------- delivery partner (own data only)
@app.get("/me")
def me(user=Depends(partner_only)):
    """The partner's profile and unread messages."""
    dp, branch = user["dp_id"], user["branch_id"]
    return _clean({"profile": partner_scope.get_partner_profile(dp, branch),
                   "unread_messages": partner_scope.get_partner_notifications(dp, branch, unread_only=True)})


@app.get("/me/deliveries")
def my_deliveries(user=Depends(partner_only)):
    """The partner's own deliveries for today."""
    df = partner_scope.get_partner_deliveries(user["dp_id"], user["branch_id"])
    return _records(df.drop(columns=["eta_min", "deadline_min"]))


@app.get("/me/route")
def my_route(user=Depends(partner_only)):
    """The partner's own route, stops and road shapes."""
    return _clean(partner_scope.get_partner_route(user["dp_id"], user["branch_id"]))


@app.get("/me/messages")
def my_messages(user=Depends(partner_only)):
    """The partner's latest messages."""
    return partner_scope.get_partner_notifications(user["dp_id"], user["branch_id"])


@app.post("/me/messages/read")
def read_my_messages(user=Depends(partner_only)):
    """Mark all of the partner's messages as read."""
    partner_scope.mark_notifications_read(user["dp_id"], user["branch_id"])
    return {"ok": True}


@app.post("/me/deliveries/{delivery_id}/delivered")
def deliver(delivery_id: str, user=Depends(partner_only)):
    """Mark one of the partner's deliveries as delivered (409 if a step was skipped)."""
    try:
        changed = _forbidden(lambda: partner_scope.mark_delivered(user["dp_id"], user["branch_id"], delivery_id))
    except ValueError as error:  # e.g. not picked up yet – steps can't be skipped
        raise HTTPException(409, str(error)) from error
    return {"ok": True, "changed": changed}


@app.post("/me/location")
def my_location(body: LocationIn, user=Depends(partner_only)):
    """The partner's phone reports its position (every 30 s while on duty). Ignored outside Coimbatore."""
    used = tracking.record(user["dp_id"], user["branch_id"], body.lat, body.lng, body.accuracy_m)
    return {"ok": True, "used": used}


@app.get("/me/offers")
def my_offers(user=Depends(partner_only)):
    """Orders offered to the partner that still need Accept / Can't take."""
    return _clean(escalation.partner_offers(user["dp_id"], user["branch_id"]))


@app.post("/me/deliveries/{delivery_id}/decline")
def decline(delivery_id: str, body: DeclineIn, user=Depends(partner_only)):
    """Can't take an offered order: it goes back to the queue and the admin is alerted."""
    try:
        result = _forbidden(lambda: escalation.respond(user["dp_id"], user["branch_id"], delivery_id, False,
                                                      reason=body.reason))
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return {"ok": True, "offer": result}


@app.post("/me/deliveries/{delivery_id}/pod/code")
def send_pod_code(delivery_id: str, user=Depends(partner_only)):
    """Send the customer a 4-digit delivery code (WhatsApp; in Demo mode the code comes back as demo_code)."""
    return _forbidden(lambda: pod.send_code(user["dp_id"], user["branch_id"], delivery_id))


@app.post("/me/deliveries/{delivery_id}/pod")
async def deliver_with_proof(delivery_id: str, photo: UploadFile | None = File(None),
                             signature: UploadFile | None = File(None), code: str | None = Form(None),
                             note: str = Form(""), user=Depends(partner_only)):
    """Delivered with proof: a photo plus the customer's code or a signature (PNG). Required for medical orders."""
    photo_bytes = await photo.read() if photo else None
    signature_bytes = await signature.read() if signature else None
    try:
        _forbidden(lambda: pod.complete(user["dp_id"], user["branch_id"], delivery_id, photo=photo_bytes,
                                        signature=signature_bytes, code=code, note=note))
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return {"ok": True, "delivered": delivery_id}


@app.post("/me/deliveries/{delivery_id}/{step}")
def advance(delivery_id: str, step: str, user=Depends(partner_only)):
    """step: accepted | picked_up | in_transit (Accept -> Picked up -> Start), in order."""
    if step not in ("accepted", "picked_up", "in_transit"):
        raise HTTPException(404, "Unknown step")
    try:
        changed = _forbidden(
            lambda: partner_scope.advance_delivery(user["dp_id"], user["branch_id"], delivery_id, step)
        )
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    return {"ok": True, "changed": changed}


@app.get("/me/issues")
def my_issues(user=Depends(partner_only)):
    """Issues the partner has reported and what happened to them."""
    return _clean(partner_scope.get_partner_incidents(user["dp_id"], user["branch_id"]))


@app.post("/me/issues/preview")
async def preview_my_issue(text: str = Form(""), quick_type: str | None = Form(None),
                           audio: UploadFile | None = File(None), user=Depends(partner_only)):
    """Show what the AI understood from text and/or a voice note, without saving anything."""
    audio_bytes = await audio.read() if audio else None
    return _clean(partner_scope.preview_issue(user["dp_id"], user["branch_id"], text=text, audio=audio_bytes,
                                              quick_type=quick_type))


def _my_incident(user, issue_id):
    return next(i for i in partner_scope.get_partner_incidents(user["dp_id"], user["branch_id"])
                if i["issue_id"] == issue_id)


@app.post("/me/issues", status_code=201)
def report_my_issue(body: IssueIn, user=Depends(partner_only)):
    """Report a problem by text; the branch gets an alert with an impact analysis."""
    dp, branch = user["dp_id"], user["branch_id"]
    seen = partner_scope.preview_issue(dp, branch, text=body.text, quick_type=body.quick_type)
    if seen["problem"] is None:
        raise HTTPException(422, "Say what happened: text or quick_type is required")
    issue_id = _forbidden(lambda: partner_scope.report_issue(dp, branch, _with_location(seen["problem"], body.road_id),
                                                             transcript=seen["transcript"],
                                                             quick_type=body.quick_type))
    return _my_incident(user, issue_id)


@app.post("/me/issues/voice", status_code=201)
async def report_my_voice_issue(audio: UploadFile = File(...), quick_type: str | None = Form(None),
                                user=Depends(partner_only)):
    """Report a problem by voice note; same flow as a typed report."""
    dp, branch = user["dp_id"], user["branch_id"]
    audio_bytes = await audio.read()
    seen = partner_scope.preview_issue(dp, branch, audio=audio_bytes, quick_type=quick_type)
    if seen["problem"] is None:
        raise HTTPException(422, "Could not understand the voice note; send text instead")
    issue_id = partner_scope.report_issue(dp, branch, seen["problem"], transcript=seen["transcript"],
                                          engine=seen["engine"], audio=audio_bytes, quick_type=quick_type)
    return _my_incident(user, issue_id)


# ---------------------------------------------------------------- Branch Admin (own branch only)
@app.get("/kpis")
def kpis(user=Depends(branch_admin_only)):
    """The branch's live KPIs (deliveries, delays, critical, open alerts)."""
    return _clean(operations.kpis(user["branch_id"]))


@app.get("/partners")
def partners(user=Depends(branch_admin_only)):
    """The branch's delivery partners with vehicle, load and status."""
    return _records(store.partners_df(user["branch_id"]))


@app.get("/partners/{partner_id}")
def partner(partner_id: str, user=Depends(branch_admin_only)):
    """One partner of the branch with stops, messages and latest reports (404 if not in this branch)."""
    p = store.get_partner(partner_id, user["branch_id"])
    if p is None:
        raise HTTPException(404, f"No delivery partner {partner_id} in your branch")
    stops = store.deliveries_df(p["vehicle_id"], branch_id=user["branch_id"]).drop(columns=["eta_min", "deadline_min"])
    return {"partner": _clean(p), "stops": _records(stops), "messages": store.messages_for(partner_id),
            "reports": [_public(i) for i in store.list_issues(partner_id=partner_id, branch_id=user["branch_id"])[:5]]}


@app.get("/deliveries")
def deliveries(user=Depends(branch_admin_only)):
    """All deliveries of the branch."""
    return _records(store.deliveries_df(branch_id=user["branch_id"]).drop(columns=["eta_min", "deadline_min"]))


@app.get("/map")
def live_map(user=Depends(branch_admin_only)):
    """Everything a map screen needs for the admin's branch: partners, deliveries, roads, blocks, detours."""
    branch = user["branch_id"]
    roads = load_all()["roads"][["road_id", "name", "points"]]
    open_plans = [i["plan"] for i in store.list_issues(store.OPEN_ISSUE_STATUSES, branch_id=branch) if i.get("plan")]
    accepted = [i["plan"] for i in store.list_issues(("accepted",), branch_id=branch) if i.get("plan")]
    return {
        "partners": _records(store.partners_df(branch)),
        "deliveries": _records(store.deliveries_df(branch_id=branch).drop(columns=["eta_min", "deadline_min"])),
        "roads": _records(roads),
        "blocked": _clean(
            store.active_disruptions(branch) + [p["disruption"] for p in open_plans if p.get("disruption")]
        ),
        "detour_roads": sorted({r for p in open_plans + accepted for r in p.get("via_roads", [])}),
        "at_risk": {r["delivery_id"]: r["risk_label"] for p in open_plans for r in p.get("risk", [])},
    }


@app.get("/insights")
def insights(user=Depends(branch_admin_only)):
    """How the branch decides on recommendations: acceptance by action type, most changed, the model."""
    data = learning.insights(user["branch_id"])
    data["recent"] = [{k: r[k] for k in ("time", "decision", "action_type", "title", "reason")} for r in data["recent"]]
    return _clean(data)


@app.get("/escalations")
def escalations(user=Depends(branch_admin_only)):
    """Orders nobody accepted in time or a partner can't take, each with the suggested partner."""
    return _clean(escalation.admin_alerts(user["branch_id"]))


@app.get("/issues")
def list_issues(open: bool = False, user=Depends(branch_admin_only)):
    """Issues of the branch; open=true for the ones still waiting."""
    return [_public(i) for i in store.list_issues(store.OPEN_ISSUE_STATUSES if open else None,
                                                  branch_id=user["branch_id"])]


@app.get("/issues/{issue_id}")
def get_issue(issue_id: int, user=Depends(branch_admin_only)):
    """One issue of the branch with its analysis and plan."""
    return _public(_issue_or_404(issue_id, user["branch_id"]))


@app.get("/issues/{issue_id}/audio")
def issue_audio(issue_id: int, user=Depends(branch_admin_only)):
    """The voice note attached to an issue (404 if there is none)."""
    issue = _issue_or_404(issue_id, user["branch_id"])
    if not issue.get("audio"):
        raise HTTPException(404, "This issue has no voice note")
    return Response(issue["audio"], media_type="audio/wav")


@app.post("/issues", status_code=201)
def log_issue(body: AdminIssueIn, user=Depends(branch_admin_only)):
    """The branch admin logs a problem heard by phone (for a partner of the branch, or the desk)."""
    branch = user["branch_id"]
    if body.partner_id != "OPS" and store.get_partner(body.partner_id, branch) is None:
        raise HTTPException(403, f"{body.partner_id} is not in your branch")
    seen = issues.preview(body.partner_id, text=body.text, quick_type=body.quick_type, branch_id=branch)
    if seen["problem"] is None:
        raise HTTPException(422, "Say what happened: text or quick_type is required")
    issue_id = issues.submit(body.partner_id, _with_location(seen["problem"], body.road_id),
                             transcript=seen["transcript"], quick_type=body.quick_type, source="manager",
                             branch_id=branch)
    return _public(store.get_issue(issue_id, branch))


@app.patch("/issues/{issue_id}")
def edit_issue(issue_id: int, body: IssueEdit, user=Depends(branch_admin_only)):
    """Correct the issue type, road, severity or duration, then re-run the analysis."""
    _issue_or_404(issue_id, user["branch_id"])
    operations.edit_problem(issue_id, branch_id=user["branch_id"], **body.model_dump())
    return _public(store.get_issue(issue_id, user["branch_id"]))


@app.post("/issues/{issue_id}/accept")
def accept(issue_id: int, user=Depends(branch_admin_only)):
    """Accept the recommended plan: routes, ETAs, messages and history update in one transaction."""
    issue = _issue_or_404(issue_id, user["branch_id"])
    if issue["status"] != "analysed":
        raise HTTPException(409, f"Issue is '{issue['status']}', not waiting for a decision")
    summary = operations.accept(issue_id, decided_by=user["display_name"], branch_id=user["branch_id"])
    return {
        "summary": summary,
        "issue": _public(store.get_issue(issue_id)),
        "kpis": _clean(operations.kpis(user["branch_id"])),
    }


@app.post("/issues/{issue_id}/reject")
def reject(issue_id: int, body: Decision, user=Depends(branch_admin_only)):
    """Reject the plan with a reason; the reporter is told."""
    _issue_or_404(issue_id, user["branch_id"])
    operations.reject(issue_id, body.reason, user["display_name"], branch_id=user["branch_id"])
    return _public(store.get_issue(issue_id))


# ---------------------------------------------------------------- Twilio voice webhooks (signed requests only)
async def _twilio_form(request):
    """The POSTed form, after checking X-Twilio-Signature against PUBLIC_BASE_URL + path + query."""
    form = {k: str(v) for k, v in (await request.form()).items()}
    base = str(setting("PUBLIC_BASE_URL", "")).rstrip("/")
    url = f"{base}{request.url.path}" + (f"?{request.url.query}" if request.url.query else "")
    if not voice_call.valid_request(url, form, request.headers.get("X-Twilio-Signature", "")):
        raise HTTPException(403, "Invalid Twilio signature")
    return form


def _twiml(text):
    return Response(content=text, media_type="application/xml")


@app.post("/twilio/voice", tags=["twilio"])
async def twilio_voice(request: Request, delivery_id: str, dp_id: str):
    """The call script (TwiML): the offer, then one key – 1 accept, 2 can't take (speech works too)."""
    await _twilio_form(request)
    offer = escalation.call_offer(delivery_id, dp_id)
    if offer is None:
        return _twiml(voice_call.twiml_say("This order is no longer waiting for you. Goodbye."))
    gather = voice_call.webhook_url("/twilio/gather", delivery_id, dp_id)
    return _twiml(voice_call.twiml_offer(escalation.call_message(offer), gather))


@app.post("/twilio/gather", tags=["twilio"])
async def twilio_gather(request: Request, delivery_id: str, dp_id: str):
    """The partner's answer on the call; updates the order in one transaction."""
    form = await _twilio_form(request)
    answer = voice_call.read_answer(form.get("Digits"), form.get("SpeechResult"))
    if answer is None:
        again = voice_call.webhook_url("/twilio/voice", delivery_id, dp_id)
        return _twiml(voice_call.twiml_say("Sorry, I did not get that.", redirect_url=again))
    try:
        escalation.respond_by_call(delivery_id, dp_id, answer)
    except (PermissionError, ValueError):
        return _twiml(voice_call.twiml_say("This order is no longer waiting for you. Goodbye."))
    if answer == "accept":
        return _twiml(voice_call.twiml_say("Thank you. The order is yours. Drive safe."))
    return _twiml(voice_call.twiml_say("Okay. We will give it to someone else. Thank you."))
