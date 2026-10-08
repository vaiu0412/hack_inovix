"""Ripple REST API – the same logic and database as the Streamlit app, for a native mobile app.

Run:   uvicorn api.main:app --reload
Docs:  http://localhost:8000/docs   (click "Authorize" and paste the token from POST /login)

Auth:  POST /login {role, user_id, password} -> {"token": ...}; send "Authorization: Bearer <token>".
       Tokens are HMAC-signed with RIPPLE_SECRET_KEY (set it in production) and last 12 hours.
       Partner endpoints live under /me and take the partner's ID ONLY from the token.
       Every other endpoint needs a manager token.
"""
import base64
import hashlib
import hmac
import json
import os
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from modules import auth, issues, operations, partner_scope, store
from modules.data_loader import load_all

SECRET_KEY = (os.getenv("RIPPLE_SECRET_KEY") or "dev-only-change-me").encode()
TOKEN_SECONDS = 12 * 3600


@asynccontextmanager
async def lifespan(_app):
    store.init_db()
    yield


app = FastAPI(title="Ripple API", version="3.0", lifespan=lifespan,
              description="Disruption-aware delivery operations: login, partners, deliveries, issues and AI plans.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- tokens
def _b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def make_token(user):
    payload = {"sub": user["user_id"], "role": user["role"], "dp": user.get("dp_id"),
               "exp": int(time.time()) + TOKEN_SECONDS}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(SECRET_KEY, body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{signature}"


def read_token(token):
    """Payload of a valid, unexpired token for an account that still exists – else None."""
    try:
        body, signature = token.split(".")
        expected = hmac.new(SECRET_KEY, body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:
        return None
    if payload.get("exp", 0) < time.time():
        return None
    user = auth.get_user(payload.get("sub"))
    if not user or user["role"] != payload.get("role"):
        return None
    return payload


def current_user(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Sign in first: POST /login, then send 'Authorization: Bearer <token>'")
    payload = read_token(authorization.split(" ", 1)[1].strip())
    if payload is None:
        raise HTTPException(401, "Invalid or expired token")
    return payload


def manager_only(user=Depends(current_user)):
    if user["role"] != "manager":
        raise HTTPException(403, "Managers only")
    return user


def partner_only(user=Depends(current_user)):
    if user["role"] != "partner" or not user.get("dp"):
        raise HTTPException(403, "Delivery partners only")
    return user


# ---------------------------------------------------------------- models + helpers
class LoginIn(BaseModel):
    role: str
    user_id: str
    password: str


class IssueIn(BaseModel):
    text: str = ""
    quick_type: Optional[str] = None
    road_id: Optional[str] = None  # when the reporter picked the road by hand


class ManagerIssueIn(IssueIn):
    partner_id: str = "OPS"  # who is affected, or the operations desk


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


def _issue_or_404(issue_id):
    issue = store.get_issue(issue_id)
    if issue is None:
        raise HTTPException(404, f"Unknown issue {issue_id}")
    return issue


def _with_location(problem, road_id):
    return issues.set_location(problem, road_id, {"roads": load_all()["roads"]}) if road_id else problem


# ---------------------------------------------------------------- public
@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/login")
def login(body: LoginIn):
    user, error = auth.login(body.role, body.user_id, body.password)
    if error:
        status = 429 if "Too many attempts" in error else 403 if "belongs to" in error else 401
        raise HTTPException(status, error)
    return {"token": make_token(user), "token_type": "bearer", "expires_in": TOKEN_SECONDS, "role": user["role"],
            "user_id": user["user_id"], "display_name": user["display_name"], "dp_id": user["dp_id"]}


# ---------------------------------------------------------------- delivery partner (own data only)
@app.get("/me")
def me(user=Depends(partner_only)):
    dp = user["dp"]
    return _clean({"profile": partner_scope.get_partner_profile(dp),
                   "unread_messages": partner_scope.get_partner_notifications(dp, unread_only=True)})


@app.get("/me/deliveries")
def my_deliveries(user=Depends(partner_only)):
    return _records(partner_scope.get_partner_deliveries(user["dp"]).drop(columns=["eta_min", "deadline_min"]))


@app.get("/me/route")
def my_route(user=Depends(partner_only)):
    return _clean(partner_scope.get_partner_route(user["dp"]))


@app.get("/me/messages")
def my_messages(user=Depends(partner_only)):
    return partner_scope.get_partner_notifications(user["dp"])


@app.post("/me/messages/read")
def read_my_messages(user=Depends(partner_only)):
    partner_scope.mark_notifications_read(user["dp"])
    return {"ok": True}


@app.post("/me/deliveries/{delivery_id}/delivered")
def deliver(delivery_id: str, user=Depends(partner_only)):
    try:
        changed = partner_scope.mark_delivered(user["dp"], delivery_id)
    except PermissionError as error:
        raise HTTPException(403, str(error))
    return {"ok": True, "changed": changed}


@app.get("/me/issues")
def my_issues(user=Depends(partner_only)):
    return _clean(partner_scope.get_partner_incidents(user["dp"]))


@app.post("/me/issues/preview")
async def preview_my_issue(text: str = Form(""), quick_type: Optional[str] = Form(None),
                           audio: Optional[UploadFile] = File(None), user=Depends(partner_only)):
    audio_bytes = await audio.read() if audio else None
    return _clean(partner_scope.preview_issue(user["dp"], text=text, audio=audio_bytes, quick_type=quick_type))


@app.post("/me/issues", status_code=201)
def report_my_issue(body: IssueIn, user=Depends(partner_only)):
    seen = partner_scope.preview_issue(user["dp"], text=body.text, quick_type=body.quick_type)
    if seen["problem"] is None:
        raise HTTPException(422, "Say what happened: text or quick_type is required")
    try:
        issue_id = partner_scope.report_issue(user["dp"], _with_location(seen["problem"], body.road_id),
                                              transcript=seen["transcript"], quick_type=body.quick_type)
    except PermissionError as error:
        raise HTTPException(403, str(error))
    return next(i for i in partner_scope.get_partner_incidents(user["dp"]) if i["issue_id"] == issue_id)


@app.post("/me/issues/voice", status_code=201)
async def report_my_voice_issue(audio: UploadFile = File(...), quick_type: Optional[str] = Form(None),
                                user=Depends(partner_only)):
    audio_bytes = await audio.read()
    seen = partner_scope.preview_issue(user["dp"], audio=audio_bytes, quick_type=quick_type)
    if seen["problem"] is None:
        raise HTTPException(422, "Could not understand the voice note; send text instead")
    issue_id = partner_scope.report_issue(user["dp"], seen["problem"], transcript=seen["transcript"],
                                          engine=seen["engine"], audio=audio_bytes, quick_type=quick_type)
    return next(i for i in partner_scope.get_partner_incidents(user["dp"]) if i["issue_id"] == issue_id)


# ---------------------------------------------------------------- manager
@app.get("/kpis")
def kpis(_=Depends(manager_only)):
    return _clean(operations.kpis())


@app.get("/partners")
def partners(_=Depends(manager_only)):
    return _records(store.partners_df())


@app.get("/partners/{partner_id}")
def partner(partner_id: str, _=Depends(manager_only)):
    p = store.get_partner(partner_id)
    if p is None:
        raise HTTPException(404, f"Unknown delivery partner {partner_id}")
    stops = store.deliveries_df(p["vehicle_id"]).drop(columns=["eta_min", "deadline_min"])
    return {"partner": _clean(p), "stops": _records(stops), "messages": store.messages_for(partner_id),
            "reports": [_public(i) for i in store.list_issues(partner_id=partner_id)[:5]]}


@app.get("/deliveries")
def deliveries(vehicle_id: Optional[str] = None, _=Depends(manager_only)):
    return _records(store.deliveries_df(vehicle_id).drop(columns=["eta_min", "deadline_min"]))


@app.get("/map")
def live_map(_=Depends(manager_only)):
    """Everything a map screen needs: partners, deliveries, roads, blocked roads and detours."""
    roads = load_all()["roads"][["road_id", "name", "points"]]
    open_plans = [i["plan"] for i in store.list_issues(store.OPEN_ISSUE_STATUSES) if i.get("plan")]
    accepted = [i["plan"] for i in store.list_issues(("accepted",)) if i.get("plan")]
    return {
        "partners": _records(store.partners_df()),
        "deliveries": _records(store.deliveries_df().drop(columns=["eta_min", "deadline_min"])),
        "roads": _records(roads),
        "blocked": _clean(store.active_disruptions() + [p["disruption"] for p in open_plans if p.get("disruption")]),
        "detour_roads": sorted({r for p in open_plans + accepted for r in p.get("via_roads", [])}),
        "at_risk": {r["delivery_id"]: r["risk_label"] for p in open_plans for r in p.get("risk", [])},
    }


@app.get("/issues")
def list_issues(open: bool = False, partner_id: Optional[str] = None, _=Depends(manager_only)):
    return [_public(i) for i in store.list_issues(store.OPEN_ISSUE_STATUSES if open else None, partner_id)]


@app.get("/issues/{issue_id}")
def get_issue(issue_id: int, _=Depends(manager_only)):
    return _public(_issue_or_404(issue_id))


@app.get("/issues/{issue_id}/audio")
def issue_audio(issue_id: int, _=Depends(manager_only)):
    issue = _issue_or_404(issue_id)
    if not issue.get("audio"):
        raise HTTPException(404, "This issue has no voice note")
    return Response(issue["audio"], media_type="audio/wav")


@app.post("/issues", status_code=201)
def log_issue(body: ManagerIssueIn, _=Depends(manager_only)):
    """The manager logs a problem heard by phone (for a partner or the operations desk)."""
    seen = issues.preview(body.partner_id, text=body.text, quick_type=body.quick_type)
    if seen["problem"] is None:
        raise HTTPException(422, "Say what happened: text or quick_type is required")
    issue_id = issues.submit(body.partner_id, _with_location(seen["problem"], body.road_id),
                             transcript=seen["transcript"], quick_type=body.quick_type, source="manager")
    return _public(store.get_issue(issue_id))


@app.patch("/issues/{issue_id}")
def edit_issue(issue_id: int, body: IssueEdit, _=Depends(manager_only)):
    _issue_or_404(issue_id)
    operations.edit_problem(issue_id, **body.model_dump())
    return _public(store.get_issue(issue_id))


@app.post("/issues/{issue_id}/accept")
def accept(issue_id: int, user=Depends(manager_only)):
    issue = _issue_or_404(issue_id)
    if issue["status"] != "analysed":
        raise HTTPException(409, f"Issue is '{issue['status']}', not waiting for a decision")
    name = (auth.get_user(user["sub"]) or {}).get("display_name", "Manager")
    summary = operations.accept(issue_id, decided_by=name)
    return {"summary": summary, "issue": _public(store.get_issue(issue_id)), "kpis": _clean(operations.kpis())}


@app.post("/issues/{issue_id}/reject")
def reject(issue_id: int, body: Decision, user=Depends(manager_only)):
    _issue_or_404(issue_id)
    operations.reject(issue_id, body.reason, (auth.get_user(user["sub"]) or {}).get("display_name", "Manager"))
    return _public(store.get_issue(issue_id))


@app.post("/demo/reset")
def reset(_=Depends(manager_only)):
    store.reset_demo()
    return {"ok": True}
