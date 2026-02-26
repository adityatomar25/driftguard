"""FastAPI backend for DriftGuard dashboard."""

import os
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from driftguard.models import DriftEvent, AuditEntry, init_db, get_session
from driftguard.storage import Storage

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

DB_URL = os.environ.get("DRIFTGUARD_DB_URL", "sqlite:///driftguard.db")
storage = Storage(DB_URL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db(DB_URL)
    yield

app = FastAPI(title="DriftGuard API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _event_to_dict(e: DriftEvent) -> dict:
    return {
        "id": e.id,
        "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        "terraform_address": e.terraform_address,
        "resource_type": e.resource_type,
        "env": e.env,
        "actions": e.actions,
        "before": e.before,
        "after": e.after,
        "diff_summary": e.diff_summary,
        "classification": e.classification,
        "risk_score": e.risk_score,
        "decision": e.decision,
        "status": e.status,
        "reconciler_output": e.reconciler_output,
        "actor": e.actor,
    }


def _audit_to_dict(a: AuditEntry) -> dict:
    return {
        "id": a.id,
        "timestamp": a.timestamp.isoformat() if a.timestamp else None,
        "event_id": a.event_id,
        "action": a.action,
        "details": a.details,
        "actor": a.actor,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/events")
def list_events(
    env: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
):
    events = storage.list_events(env=env, status=status, limit=limit, offset=offset)
    return [_event_to_dict(e) for e in events]


@app.get("/api/events/{event_id}")
def get_event(event_id: str):
    ev = storage.get_event(event_id)
    if ev is None:
        raise HTTPException(404, "Event not found")
    return _event_to_dict(ev)


class ActionRequest(BaseModel):
    action: str  # reconcile | ignore | manual
    comment: str = ""


@app.post("/api/events/{event_id}/action")
def perform_action(event_id: str, body: ActionRequest):
    ev = storage.get_event(event_id)
    if ev is None:
        raise HTTPException(404, "Event not found")
    storage.update_event(event_id, decision=body.action, status="pending")
    storage.log_audit(f"manual_{body.action}", event_id, body.comment, actor="dashboard_user")
    return {"status": "ok", "event_id": event_id, "action": body.action}


@app.get("/api/metrics")
def metrics():
    return storage.counts()


@app.get("/api/audit")
def audit_log(limit: int = Query(200, le=1000)):
    entries = storage.list_audit(limit=limit)
    return [_audit_to_dict(a) for a in entries]
