"""FastAPI backend for DriftGuard dashboard."""

import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
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


# ---------------------------------------------------------------------------
# Seed demo data
# ---------------------------------------------------------------------------

@app.post("/api/seed")
def seed_demo_data(count: int = Query(12, ge=1, le=500), reset: bool = False):
    """Populate the database with realistic demo drift events + audit trail.

    Query params:
        count: number of events to create (default 12, max 500)
        reset: if true, wipe existing data first
    """
    import random
    from datetime import timedelta

    # Reset if requested
    if reset:
        session = get_session()
        session.query(AuditEntry).delete()
        session.query(DriftEvent).delete()
        session.commit()
    else:
        current = storage.counts()
        if current["total"] > 0:
            return {"message": "Database already has data. Use ?reset=true to wipe and re-seed.", "total": current["total"]}

    now = datetime.now(timezone.utc)

    # --- Resource templates (picked at random) ---
    resource_pool = [
        {"terraform_address": "aws_security_group.web_sg", "resource_type": "aws_security_group",
         "diff_summary": "- ingress.0.cidr_blocks.0: 10.0.0.0/8\n+ ingress.0.cidr_blocks.0: 0.0.0.0/0"},
        {"terraform_address": "aws_instance.api_server", "resource_type": "aws_instance",
         "diff_summary": "- instance_type: t3.medium\n+ instance_type: t3.xlarge"},
        {"terraform_address": "aws_s3_bucket.logs", "resource_type": "aws_s3_bucket",
         "diff_summary": "- tags.ManagedBy: terraform\n+ tags.ManagedBy: manual"},
        {"terraform_address": "aws_instance.worker_1", "resource_type": "aws_instance",
         "diff_summary": "- ami: ami-0abcdef1234567890\n+ ami: ami-0fedcba0987654321"},
        {"terraform_address": "aws_rds_cluster.main_db", "resource_type": "aws_rds_cluster",
         "diff_summary": "- engine_version: 14.6\n+ engine_version: 15.2\n- backup_retention_period: 7\n+ backup_retention_period: 1"},
        {"terraform_address": "aws_security_group.internal", "resource_type": "aws_security_group",
         "diff_summary": "~ entire resource deleted manually"},
        {"terraform_address": "docker_container.nginx", "resource_type": "docker_container",
         "diff_summary": "- env.0: NODE_ENV=production\n+ env.0: NODE_ENV=development"},
        {"terraform_address": "aws_lambda_function.processor", "resource_type": "aws_lambda_function",
         "diff_summary": "- timeout: 30\n+ timeout: 120"},
        {"terraform_address": "aws_iam_role.admin_role", "resource_type": "aws_iam_role",
         "diff_summary": "- assume_role_policy: ...restricted...\n+ assume_role_policy: ...wildcard *..."},
        {"terraform_address": "aws_instance.batch_worker", "resource_type": "aws_instance",
         "diff_summary": "+ new instance created outside Terraform"},
        {"terraform_address": "aws_cloudwatch_log_group.app", "resource_type": "aws_cloudwatch_log_group",
         "diff_summary": "- retention_in_days: 30\n+ retention_in_days: 14"},
        {"terraform_address": "aws_autoscaling_group.web_asg", "resource_type": "aws_autoscaling_group",
         "diff_summary": "- desired_capacity: 3\n+ desired_capacity: 10"},
        {"terraform_address": "aws_vpc.main", "resource_type": "aws_vpc",
         "diff_summary": "- enable_dns_hostnames: true\n+ enable_dns_hostnames: false"},
        {"terraform_address": "aws_eks_cluster.primary", "resource_type": "aws_eks_cluster",
         "diff_summary": "- version: 1.28\n+ version: 1.27"},
        {"terraform_address": "aws_elasticache_cluster.redis", "resource_type": "aws_elasticache_cluster",
         "diff_summary": "- node_type: cache.t3.micro\n+ node_type: cache.r6g.large"},
        {"terraform_address": "aws_sqs_queue.events", "resource_type": "aws_sqs_queue",
         "diff_summary": "- visibility_timeout_seconds: 30\n+ visibility_timeout_seconds: 300"},
        {"terraform_address": "aws_sns_topic.alerts", "resource_type": "aws_sns_topic",
         "diff_summary": "- kms_master_key_id: alias/aws/sns\n+ kms_master_key_id: (removed)"},
        {"terraform_address": "aws_dynamodb_table.sessions", "resource_type": "aws_dynamodb_table",
         "diff_summary": "- billing_mode: PAY_PER_REQUEST\n+ billing_mode: PROVISIONED"},
        {"terraform_address": "aws_route53_record.api", "resource_type": "aws_route53_record",
         "diff_summary": "- ttl: 300\n+ ttl: 60"},
        {"terraform_address": "aws_ecr_repository.app", "resource_type": "aws_ecr_repository",
         "diff_summary": "- image_scanning_configuration.scan_on_push: true\n+ image_scanning_configuration.scan_on_push: false"},
        {"terraform_address": "aws_kms_key.data", "resource_type": "aws_kms_key",
         "diff_summary": "- enable_key_rotation: true\n+ enable_key_rotation: false"},
        {"terraform_address": "aws_cloudfront_distribution.cdn", "resource_type": "aws_cloudfront_distribution",
         "diff_summary": "- price_class: PriceClass_100\n+ price_class: PriceClass_All"},
        {"terraform_address": "docker_container.redis", "resource_type": "docker_container",
         "diff_summary": "- image: redis:7.0\n+ image: redis:6.2"},
        {"terraform_address": "aws_db_instance.replica", "resource_type": "aws_db_instance",
         "diff_summary": "- multi_az: true\n+ multi_az: false"},
    ]

    envs = ["prod", "staging", "dev"]
    actions_pool = [["update"], ["delete"], ["create"], ["replace"], ["update"]]
    classifications = ["require_approval", "auto_reconcile", "alert", "ignore"]
    statuses_by_decision = {
        "manual": ["pending", "pending", "failed"],
        "reconcile": ["reconciled", "reconciled", "reconciled", "failed"],
        "alert": ["detected"],
        "ignore": ["ignored"],
    }
    reconcile_outputs_ok = [
        "Apply complete! Resources: 0 added, 1 changed, 0 destroyed.",
        "Apply complete! Resources: 1 added, 0 changed, 1 destroyed.",
        "Apply complete! Resources: 0 added, 2 changed, 0 destroyed.",
    ]
    reconcile_outputs_err = [
        "Error: Provider produced inconsistent final plan",
        "Error: resource has been deleted outside of Terraform",
        "Error: timeout waiting for state to become 'running'",
    ]

    created = 0
    for i in range(count):
        tpl = random.choice(resource_pool)
        # Make address unique by appending index for duplicates
        address = tpl["terraform_address"] if i < len(resource_pool) else f"{tpl['terraform_address']}_{i}"
        env = random.choice(envs)
        actions = random.choice(actions_pool)
        classification = random.choice(classifications)
        risk_score = round(random.uniform(1.0, 10.0), 1)

        # Decide
        if classification == "require_approval":
            decision = "manual"
        elif classification == "auto_reconcile":
            decision = "reconcile"
        elif classification == "ignore":
            decision = "ignore"
        else:
            decision = "alert"

        status = random.choice(statuses_by_decision[decision])

        reconciler_output = ""
        if status == "reconciled":
            reconciler_output = random.choice(reconcile_outputs_ok)
        elif status == "failed":
            reconciler_output = random.choice(reconcile_outputs_err)

        evt = {
            "terraform_address": address,
            "resource_type": tpl["resource_type"],
            "env": env,
            "actions": actions,
            "classification": classification,
            "risk_score": risk_score,
            "decision": decision,
            "status": status,
            "diff_summary": tpl["diff_summary"],
            "reconciler_output": reconciler_output,
        }

        hours_ago = random.randint(1, 168)  # up to 7 days
        saved = storage.save_event(evt)
        session = get_session()
        saved.timestamp = now - timedelta(hours=hours_ago)
        session.commit()

        storage.log_audit("detected", saved.id, f"actions={actions}")
        storage.log_audit("classified", saved.id, f"{classification} risk={risk_score}")
        storage.log_audit("decided", saved.id, f"decision={decision}")
        if status in ("reconciled", "failed"):
            storage.log_audit(status, saved.id, reconciler_output[:200])
        created += 1

    return {"message": f"Seeded {created} demo drift events", "total": created}
