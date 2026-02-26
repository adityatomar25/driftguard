"""Unit tests for DriftGuard storage layer."""

import os
import pytest

from driftguard.storage import Storage
from driftguard.models import init_db


@pytest.fixture
def storage(tmp_path):
    db_path = tmp_path / "test.db"
    db_url = f"sqlite:///{db_path}"
    return Storage(db_url)


class TestStorage:
    def test_save_and_get_event(self, storage):
        saved = storage.save_event({
            "terraform_address": "docker_container.demo",
            "resource_type": "docker_container",
            "env": "dev",
            "classification": "auto_reconcile",
            "risk_score": 2.0,
            "decision": "reconcile",
            "status": "detected",
        })
        assert saved.id is not None

        fetched = storage.get_event(saved.id)
        assert fetched is not None
        assert fetched.terraform_address == "docker_container.demo"

    def test_list_events(self, storage):
        storage.save_event({"terraform_address": "a.b", "resource_type": "x", "env": "dev"})
        storage.save_event({"terraform_address": "c.d", "resource_type": "y", "env": "prod"})

        all_events = storage.list_events()
        assert len(all_events) == 2

        dev_events = storage.list_events(env="dev")
        assert len(dev_events) == 1

    def test_update_event(self, storage):
        saved = storage.save_event({"terraform_address": "a.b", "resource_type": "x"})
        updated = storage.update_event(saved.id, status="reconciled")
        assert updated.status == "reconciled"

    def test_audit_log(self, storage):
        storage.log_audit("detected", event_id="test-id", details="test", actor="tester")
        entries = storage.list_audit()
        assert len(entries) == 1
        assert entries[0].action == "detected"

    def test_counts(self, storage):
        storage.save_event({"terraform_address": "a.b", "resource_type": "x", "status": "reconciled"})
        storage.save_event({"terraform_address": "c.d", "resource_type": "y", "status": "failed"})
        storage.save_event({"terraform_address": "e.f", "resource_type": "z", "status": "detected"})

        counts = storage.counts()
        assert counts["total"] == 3
        assert counts["reconciled"] == 1
        assert counts["failed"] == 1
        assert counts["pending"] == 1
