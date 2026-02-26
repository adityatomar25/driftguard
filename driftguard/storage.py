"""Storage layer – persists drift events and audit entries to SQLite via SQLAlchemy."""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from driftguard.models import (
    AuditEntry,
    DriftEvent,
    get_session,
    init_db,
)

logger = logging.getLogger(__name__)


class Storage:
    """High-level persistence helpers for drift events and audit log."""

    def __init__(self, db_url: str = "sqlite:///driftguard.db"):
        init_db(db_url)

    # ------------------------------------------------------------------
    # Drift events
    # ------------------------------------------------------------------

    def save_event(self, data: Dict[str, Any]) -> DriftEvent:
        session = get_session()
        event = DriftEvent(**data)
        session.add(event)
        session.commit()
        session.refresh(event)
        logger.info("Saved drift event %s (%s)", event.id, event.terraform_address)
        return event

    def update_event(self, event_id: str, **kwargs) -> Optional[DriftEvent]:
        session = get_session()
        event = session.get(DriftEvent, event_id)
        if event is None:
            return None
        for k, v in kwargs.items():
            setattr(event, k, v)
        session.commit()
        session.refresh(event)
        return event

    def get_event(self, event_id: str) -> Optional[DriftEvent]:
        session = get_session()
        return session.get(DriftEvent, event_id)

    def list_events(
        self,
        env: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[DriftEvent]:
        session = get_session()
        q = session.query(DriftEvent)
        if env:
            q = q.filter(DriftEvent.env == env)
        if status:
            q = q.filter(DriftEvent.status == status)
        return q.order_by(DriftEvent.timestamp.desc()).offset(offset).limit(limit).all()

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    def log_audit(self, action: str, event_id: Optional[str] = None, details: str = "", actor: str = "system"):
        session = get_session()
        entry = AuditEntry(action=action, event_id=event_id, details=details, actor=actor)
        session.add(entry)
        session.commit()

    def list_audit(self, limit: int = 200) -> List[AuditEntry]:
        session = get_session()
        return session.query(AuditEntry).order_by(AuditEntry.timestamp.desc()).limit(limit).all()

    # ------------------------------------------------------------------
    # Metrics helpers
    # ------------------------------------------------------------------

    def counts(self) -> Dict[str, int]:
        session = get_session()
        total = session.query(DriftEvent).count()
        reconciled = session.query(DriftEvent).filter(DriftEvent.status == "reconciled").count()
        failed = session.query(DriftEvent).filter(DriftEvent.status == "failed").count()
        pending = session.query(DriftEvent).filter(DriftEvent.status.in_(["detected", "pending"])).count()
        return {"total": total, "reconciled": reconciled, "failed": failed, "pending": pending}
