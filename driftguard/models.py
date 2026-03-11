"""SQLAlchemy models for DriftGuard event store and audit log."""

import uuid
import datetime
from sqlalchemy import create_engine, Column, String, Text, DateTime, Integer, Float, JSON, event
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.pool import StaticPool

Base = declarative_base()


def generate_uuid() -> str:
    return str(uuid.uuid4())


class DriftEvent(Base):
    """Represents a single detected drift on a resource."""

    __tablename__ = "drift_events"

    id = Column(String, primary_key=True, default=generate_uuid)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    terraform_address = Column(String, nullable=False)
    resource_type = Column(String, nullable=False)
    env = Column(String, default="unknown")
    actions = Column(JSON, nullable=True)          # e.g. ["update"], ["delete"]
    before = Column(JSON, nullable=True)            # resource state before
    after = Column(JSON, nullable=True)             # resource state after
    diff_summary = Column(Text, default="")
    classification = Column(String, default="unknown")  # auto_reconcile | require_approval | alert | ignore
    risk_score = Column(Float, default=0.0)
    decision = Column(String, default="pending")        # reconcile | manual | alert | ignore
    status = Column(String, default="detected")         # detected | pending | reconciled | failed
    reconciler_output = Column(Text, default="")
    actor = Column(String, default="system")
    plan_path = Column(String, default="")


class AuditEntry(Base):
    """Immutable audit trail for every action taken."""

    __tablename__ = "audit_log"

    id = Column(String, primary_key=True, default=generate_uuid)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    event_id = Column(String, nullable=True)
    action = Column(String, nullable=False)       # detected | classified | decided | reconciled | verified | failed
    details = Column(Text, default="")
    actor = Column(String, default="system")


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

_engine = None
_SessionLocal = None


def init_db(db_url: str = "sqlite:///driftguard.db"):
    """Initialise the database engine and create tables."""
    global _engine, _SessionLocal

    connect_args = {}
    pool_kwargs = {}

    # SQLite needs special handling: single connection with WAL mode
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        pool_kwargs["poolclass"] = StaticPool

    _engine = create_engine(
        db_url,
        echo=False,
        future=True,
        connect_args=connect_args,
        **pool_kwargs,
    )

    # Enable WAL mode for SQLite – allows concurrent reads while writing
    if db_url.startswith("sqlite") and ":memory:" not in db_url:
        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    Base.metadata.create_all(_engine)
    _SessionLocal = sessionmaker(bind=_engine)


def get_session():
    """Return a new SQLAlchemy session."""
    if _SessionLocal is None:
        init_db()
    return _SessionLocal()
