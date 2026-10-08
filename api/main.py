"""Ripple REST API – the same logic and database as the Streamlit app, for a native mobile app.

Run:   uvicorn api.main:app --reload
Docs:  http://localhost:8000/docs   (try every endpoint in the browser)

Typical partner-app flow:
  GET  /partners/DP101                     -> profile, stops, unread messages
  POST /issues/preview  (form + audio)  -> "we understood ..."
  POST /issues          (json)          -> stored; AI plan ready for the manager
Typical manager-app flow:
  GET  /kpis, GET /map, GET /issues?open=true
  POST /issues/{id}/accept               -> deliveries, routes, inboxes and SMS updated
"""
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from modules import issues, operations, store
from modules.data_loader import load_all

@asynccontextmanager
async def lifespan(_app):
    store.init_db()
    yield


app = FastAPI(title="Ripple API", version="2.0", lifespan=lifespan,
              description="Disruption-aware delivery operations: partners, deliveries, issues and AI recovery plans.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------- models
class IssueIn(BaseModel):
    partner_id: str
    text: str = ""
    quick_type: Optional[str] = None
    road_id: Optional[str] = None  # when the partner picked the road by hand


class IssueEdit(BaseModel):
    type: Optional[str] = None
    road_id: Optional[str] = None
    severity: Optional[str] = None
    duration_min: Optional[int] = None


class Decision(BaseModel):
    reason: str = "Not needed"
    decided_by: str = "Manager"


def _clean(obj):
    """Plain JSON types only (pandas/numpy numbers become normal numbers)."""
    return json.loads(json.dumps(obj, default=lambda o: o.item() if hasattr(o, "item") else str(o)))


def _public(issue):
    """Issue without the raw audio bytes (fetch those from /issues/{id}/audio)."""
    out = {k: v for k, v in issue.items() if k != "audio"}
    out["has_audio"] = bool(issue.get("audio"))
    return _clean(out)


def _records(df):
    return json.loads(df.to_json(orient="records"))


def _partner_or_404(partner_id):
    partner = store.get_partner(partner_id)
    if partner is None:
        raise HTTPException(404, f"Unknown partner {partner_id}")
    return partner


def _issue_or_404(issue_id):
    issue = store.get_issue(issue_id)
    if issue is None:
        raise HTTPException(404, f"Unknown issue {issue_id}")
    return issue


# ---------------------------------------------------------------- read
@app.get("/health")
def health():
    return {"status": "ok", "db_version": store.version()}


@app.get("/kpis")
def kpis():
    return _clean(operations.kpis())


@app.get("/partners")
def partners():
    return _records(store.partners_df())


@app.get("/partners/{partner_id}")
def partner(partner_id: str):
    p = _partner_or_404(partner_id)
    stops = store.deliveries_df(p["vehicle_id"]).drop(columns=["eta_min", "deadline_min"])
    messages = store.messages_for(partner_id)
    return {"partner": _clean(p), "stops": _records(stops), "unread_messages": [m for m in messages if not m["read"]],
            "reports": [_public(i) for i in store.list_issues(partner_id=partner_id)[:5]]}


@app.get("/partners/{partner_id}/messages")
def partner_messages(partner_id: str):
    _partner_or_404(partner_id)
    return store.messages_for(partner_id, limit=50)


@app.post("/partners/{partner_id}/messages/read")
def read_messages(partner_id: str):
    _partner_or_404(partner_id)
    store.mark_messages_read(partner_id)
    return {"ok": True}


@app.get("/deliveries")
def deliveries(vehicle_id: Optional[str] = None):
    return _records(store.deliveries_df(vehicle_id).drop(columns=["eta_min", "deadline_min"]))


@app.post("/deliveries/{delivery_id}/delivered")
def delivered(delivery_id: str, partner_name: str = "Partner"):
    if delivery_id not in set(store.deliveries_df()["delivery_id"]):
        raise HTTPException(404, f"Unknown delivery {delivery_id}")
    operations.mark_delivered(delivery_id, partner_name)
    return {"ok": True}


@app.get("/map")
def live_map():
    """Everything a map screen needs: partners, deliveries, roads, blocked roads and detours."""
    roads = load_all()["roads"][["road_id", "name", "points"]]
    open_plans = [i["plan"] for i in store.list_issues(store.OPEN_ISSUE_STATUSES) if i.get("plan")]
    accepted = [i["plan"] for i in store.list_issues(("accepted",)) if i.get("plan")]
    return {
        "partners": _records(store.partners_df()),
        "deliveries": _records(store.deliveries_df().drop(columns=["eta_min", "deadline_min"])),
        "roads": _records(roads),
        "blocked": _clean(store.active_disruptions()) + [p["disruption"] for p in open_plans if p.get("disruption")],
        "detour_roads": sorted({r for p in open_plans + accepted for r in p.get("via_roads", [])}),
        "at_risk": {r["delivery_id"]: r["risk_label"] for p in open_plans for r in p.get("risk", [])},
    }


# ---------------------------------------------------------------- issues
@app.get("/issues")
def list_issues(open: bool = False, partner_id: Optional[str] = None):
    statuses = store.OPEN_ISSUE_STATUSES if open else None
    return [_public(i) for i in store.list_issues(statuses, partner_id)]


@app.get("/issues/{issue_id}")
def get_issue(issue_id: int):
    return _public(_issue_or_404(issue_id))


@app.get("/issues/{issue_id}/audio")
def issue_audio(issue_id: int):
    issue = _issue_or_404(issue_id)
    if not issue.get("audio"):
        raise HTTPException(404, "This issue has no voice note")
    return Response(issue["audio"], media_type="audio/wav")


@app.post("/issues/preview")
async def preview_issue(partner_id: str = Form(...), text: str = Form(""), quick_type: Optional[str] = Form(None),
                        audio: Optional[UploadFile] = File(None)):
    """What we understood from a voice note / text – nothing is saved."""
    audio_bytes = await audio.read() if audio else None
    return _clean(issues.preview(partner_id, text=text, audio=audio_bytes, quick_type=quick_type))


@app.post("/issues", status_code=201)
def create_issue(body: IssueIn):
    """Report a problem (text or quick type). The AI plan is ready in the response."""
    seen = issues.preview(body.partner_id, text=body.text, quick_type=body.quick_type)
    problem = seen["problem"]
    if problem is None:
        raise HTTPException(422, "Say what happened: text or quick_type is required")
    if body.road_id:
        problem = issues.set_location(problem, body.road_id, store.snapshot())
    source = "manager" if body.partner_id == "OPS" else "partner"
    issue_id = issues.submit(body.partner_id, problem, transcript=seen["transcript"], quick_type=body.quick_type,
                             source=source)
    return _public(store.get_issue(issue_id))


@app.post("/issues/voice", status_code=201)
async def create_issue_from_voice(partner_id: str = Form(...), audio: UploadFile = File(...),
                                  quick_type: Optional[str] = Form(None)):
    """Report a problem with a voice note only."""
    audio_bytes = await audio.read()
    seen = issues.preview(partner_id, audio=audio_bytes, quick_type=quick_type)
    if seen["problem"] is None:
        raise HTTPException(422, "Could not understand the voice note; send text instead")
    issue_id = issues.submit(partner_id, seen["problem"], transcript=seen["transcript"], engine=seen["engine"],
                             audio=audio_bytes, quick_type=quick_type)
    return _public(store.get_issue(issue_id))


@app.patch("/issues/{issue_id}")
def edit_issue(issue_id: int, body: IssueEdit):
    _issue_or_404(issue_id)
    operations.edit_problem(issue_id, **body.model_dump())
    return _public(store.get_issue(issue_id))


@app.post("/issues/{issue_id}/accept")
def accept(issue_id: int, body: Optional[Decision] = None):
    issue = _issue_or_404(issue_id)
    if issue["status"] != "analysed":
        raise HTTPException(409, f"Issue is '{issue['status']}', not waiting for a decision")
    summary = operations.accept(issue_id, decided_by=(body.decided_by if body else "Manager"))
    return {"summary": summary, "issue": _public(store.get_issue(issue_id)), "kpis": _clean(operations.kpis())}


@app.post("/issues/{issue_id}/reject")
def reject(issue_id: int, body: Decision):
    _issue_or_404(issue_id)
    operations.reject(issue_id, body.reason, body.decided_by)
    return _public(store.get_issue(issue_id))


@app.post("/demo/reset")
def reset():
    store.reset_demo()
    return {"ok": True}
