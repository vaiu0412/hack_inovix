"""RIPPLE REST API – the same logic, database and sessions as the Streamlit app, for a native mobile app.

Run:   uvicorn api.main:app --reload
Docs:  http://localhost:8000/docs   (click "Authorize" and paste the token from POST /login)

Auth:  POST /login {identifier, password, super_console?} -> {"token": ...} (a server-side session,
       only its hash is stored); send "Authorization: Bearer <token>"; POST /logout revokes it.
Roles: Super Admin   -> /branches (summaries), /demo/reset
       Branch Admin  -> /kpis, /partners, /deliveries, /map, /issues… – own branch only
       Delivery Partner -> /me… – own data only; dp_id and branch come from the session
"""
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from modules import auth, issues, operations, partner_scope, store
from modules.data_loader import load_all


@asynccontextmanager
async def lifespan(_app):
    store.init_db()
    yield


app = FastAPI(title="RIPPLE API", version="4.0", lifespan=lifespan,
              description="Disruption-aware delivery operations with 3-level access: Super Admin, Branch Admin, "
                          "Delivery Partner.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- sessions
def _token(authorization):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in first: POST /login, then send 'Authorization: Bearer <token>'")
    return authorization.split(" ", 1)[1].strip()


def current_user(authorization: Optional[str] = Header(None)):
    user = auth.validate_session(_token(authorization))
    if user is None:
        raise HTTPException(401, "Invalid, expired or revoked session")
    return user


def super_only(user=Depends(current_user)):
    if user["role"] != "super_admin":
        raise HTTPException(403, "Super Admins only")
    return user


def branch_admin_only(user=Depends(current_user)):
    if user["role"] != "branch_admin":
        raise HTTPException(403, "Branch Admins only")
    return user


def partner_only(user=Depends(current_user)):
    if user["role"] != "partner" or not user.get("dp_id"):
        raise HTTPException(403, "Delivery partners only")
    return user


# ---------------------------------------------------------------- models + helpers
class LoginIn(BaseModel):
    identifier: str
    password: str
    super_console: bool = False
    remember_me: bool = False


class IssueIn(BaseModel):
    text: str = ""
    quick_type: Optional[str] = None
    road_id: Optional[str] = None  # when the reporter picked the road by hand


class AdminIssueIn(IssueIn):
    partner_id: str = "OPS"  # who is affected (a partner of the branch), or the operations desk


class IssueEdit(BaseModel):
    type: Optional[str] = None
    road_id: Optional[str] = None
    severity: Optional[str] = None
    duration_min: Optional[int] = None


class Decision(BaseModel):
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
        raise HTTPException(403, str(error))


# ---------------------------------------------------------------- public
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/login")
def login(body: LoginIn):
    user, error = auth.authenticate(body.identifier, body.password, "super" if body.super_console else "workspace")
    if error:
        status = 429 if "Too many" in error else 403 if error in (
            auth.MESSAGES["inactive"], auth.MESSAGES["branch_inactive"], auth.MESSAGES["use_super_portal"],
            auth.MESSAGES["super_only"]) else 401
        raise HTTPException(status, error)
    token = auth.create_session(user["user_id"], remember_me=body.remember_me)
    return {"token": token, "token_type": "bearer", "user": _clean(user)}


@app.post("/logout")
def logout(authorization: Optional[str] = Header(None)):
    auth.revoke_session(_token(authorization))
    return {"ok": True}


# ---------------------------------------------------------------- Super Admin (summary level)
@app.get("/branches")
def branches(_=Depends(super_only)):
    return _records(store.branch_summaries())


@app.post("/demo/reset")
def reset(_=Depends(super_only)):
    store.reset_demo()
    return {"ok": True}


# ---------------------------------------------------------------- delivery partner (own data only)
@app.get("/me")
def me(user=Depends(partner_only)):
    dp, branch = user["dp_id"], user["branch_id"]
    return _clean({"profile": partner_scope.get_partner_profile(dp, branch),
                   "unread_messages": partner_scope.get_partner_notifications(dp, branch, unread_only=True)})


@app.get("/me/deliveries")
def my_deliveries(user=Depends(partner_only)):
    df = partner_scope.get_partner_deliveries(user["dp_id"], user["branch_id"])
    return _records(df.drop(columns=["eta_min", "deadline_min"]))


@app.get("/me/route")
def my_route(user=Depends(partner_only)):
    return _clean(partner_scope.get_partner_route(user["dp_id"], user["branch_id"]))


@app.get("/me/messages")
def my_messages(user=Depends(partner_only)):
    return partner_scope.get_partner_notifications(user["dp_id"], user["branch_id"])


@app.post("/me/messages/read")
def read_my_messages(user=Depends(partner_only)):
    partner_scope.mark_notifications_read(user["dp_id"], user["branch_id"])
    return {"ok": True}


@app.post("/me/deliveries/{delivery_id}/delivered")
def deliver(delivery_id: str, user=Depends(partner_only)):
    changed = _forbidden(lambda: partner_scope.mark_delivered(user["dp_id"], user["branch_id"], delivery_id))
    return {"ok": True, "changed": changed}


@app.get("/me/issues")
def my_issues(user=Depends(partner_only)):
    return _clean(partner_scope.get_partner_incidents(user["dp_id"], user["branch_id"]))


@app.post("/me/issues/preview")
async def preview_my_issue(text: str = Form(""), quick_type: Optional[str] = Form(None),
                           audio: Optional[UploadFile] = File(None), user=Depends(partner_only)):
    audio_bytes = await audio.read() if audio else None
    return _clean(partner_scope.preview_issue(user["dp_id"], user["branch_id"], text=text, audio=audio_bytes,
                                              quick_type=quick_type))


def _my_incident(user, issue_id):
    return next(i for i in partner_scope.get_partner_incidents(user["dp_id"], user["branch_id"])
                if i["issue_id"] == issue_id)


@app.post("/me/issues", status_code=201)
def report_my_issue(body: IssueIn, user=Depends(partner_only)):
    dp, branch = user["dp_id"], user["branch_id"]
    seen = partner_scope.preview_issue(dp, branch, text=body.text, quick_type=body.quick_type)
    if seen["problem"] is None:
        raise HTTPException(422, "Say what happened: text or quick_type is required")
    issue_id = _forbidden(lambda: partner_scope.report_issue(dp, branch, _with_location(seen["problem"], body.road_id),
                                                             transcript=seen["transcript"],
                                                             quick_type=body.quick_type))
    return _my_incident(user, issue_id)


@app.post("/me/issues/voice", status_code=201)
async def report_my_voice_issue(audio: UploadFile = File(...), quick_type: Optional[str] = Form(None),
                                user=Depends(partner_only)):
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
    return _clean(operations.kpis(user["branch_id"]))


@app.get("/partners")
def partners(user=Depends(branch_admin_only)):
    return _records(store.partners_df(user["branch_id"]))


@app.get("/partners/{partner_id}")
def partner(partner_id: str, user=Depends(branch_admin_only)):
    p = store.get_partner(partner_id, user["branch_id"])
    if p is None:
        raise HTTPException(404, f"No delivery partner {partner_id} in your branch")
    stops = store.deliveries_df(p["vehicle_id"], branch_id=user["branch_id"]).drop(columns=["eta_min", "deadline_min"])
    return {"partner": _clean(p), "stops": _records(stops), "messages": store.messages_for(partner_id),
            "reports": [_public(i) for i in store.list_issues(partner_id=partner_id, branch_id=user["branch_id"])[:5]]}


@app.get("/deliveries")
def deliveries(user=Depends(branch_admin_only)):
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
        "blocked": _clean(store.active_disruptions(branch) + [p["disruption"] for p in open_plans if p.get("disruption")]),
        "detour_roads": sorted({r for p in open_plans + accepted for r in p.get("via_roads", [])}),
        "at_risk": {r["delivery_id"]: r["risk_label"] for p in open_plans for r in p.get("risk", [])},
    }


@app.get("/issues")
def list_issues(open: bool = False, user=Depends(branch_admin_only)):
    return [_public(i) for i in store.list_issues(store.OPEN_ISSUE_STATUSES if open else None,
                                                  branch_id=user["branch_id"])]


@app.get("/issues/{issue_id}")
def get_issue(issue_id: int, user=Depends(branch_admin_only)):
    return _public(_issue_or_404(issue_id, user["branch_id"]))


@app.get("/issues/{issue_id}/audio")
def issue_audio(issue_id: int, user=Depends(branch_admin_only)):
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
    _issue_or_404(issue_id, user["branch_id"])
    operations.edit_problem(issue_id, branch_id=user["branch_id"], **body.model_dump())
    return _public(store.get_issue(issue_id, user["branch_id"]))


@app.post("/issues/{issue_id}/accept")
def accept(issue_id: int, user=Depends(branch_admin_only)):
    issue = _issue_or_404(issue_id, user["branch_id"])
    if issue["status"] != "analysed":
        raise HTTPException(409, f"Issue is '{issue['status']}', not waiting for a decision")
    summary = operations.accept(issue_id, decided_by=user["display_name"], branch_id=user["branch_id"])
    return {"summary": summary, "issue": _public(store.get_issue(issue_id)), "kpis": _clean(operations.kpis(user["branch_id"]))}


@app.post("/issues/{issue_id}/reject")
def reject(issue_id: int, body: Decision, user=Depends(branch_admin_only)):
    _issue_or_404(issue_id, user["branch_id"])
    operations.reject(issue_id, body.reason, user["display_name"], branch_id=user["branch_id"])
    return _public(store.get_issue(issue_id))
