"""Unit tests for DriftGuard API endpoints."""

import pytest
from fastapi.testclient import TestClient

from driftguard.api import app
from driftguard.models import init_db
from driftguard.storage import Storage


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    init_db(db_url)
    import driftguard.api as api_module
    api_module.storage = Storage(db_url)


@pytest.fixture
def client():
    return TestClient(app)


class TestAPI:
    def test_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_empty_events(self, client):
        resp = client.get("/api/events")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_metrics(self, client):
        resp = client.get("/api/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "reconciled" in data

    def test_create_and_list_events(self, client):
        from driftguard.api import storage
        storage.save_event({
            "terraform_address": "test.resource",
            "resource_type": "docker_container",
            "env": "dev",
            "status": "detected",
        })

        resp = client.get("/api/events")
        assert resp.status_code == 200
        events = resp.json()
        assert len(events) == 1
        assert events[0]["terraform_address"] == "test.resource"

    def test_get_event_detail(self, client):
        from driftguard.api import storage
        saved = storage.save_event({
            "terraform_address": "test.resource",
            "resource_type": "docker_container",
        })

        resp = client.get(f"/api/events/{saved.id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == saved.id

    def test_get_event_not_found(self, client):
        resp = client.get("/api/events/nonexistent")
        assert resp.status_code == 404

    def test_perform_action(self, client):
        from driftguard.api import storage
        saved = storage.save_event({
            "terraform_address": "test.resource",
            "resource_type": "docker_container",
            "status": "detected",
        })

        resp = client.post(f"/api/events/{saved.id}/action", json={"action": "reconcile", "comment": "test"})
        assert resp.status_code == 200
        assert resp.json()["action"] == "reconcile"

    def test_audit_log(self, client):
        resp = client.get("/api/audit")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
