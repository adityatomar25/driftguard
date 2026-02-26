"""Integration tests for the full DriftGuard pipeline.

These tests exercise the complete  detect → classify → decide → persist →
reconcile → verify  loop with mocked Terraform CLI calls, ensuring all
modules work together correctly end-to-end.
"""

import json
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from driftguard.pipeline import Pipeline, PipelineResult


# ---------------------------------------------------------------------------
# Fixture: a temporary workspace with a real config.yml + temp SQLite DB
# ---------------------------------------------------------------------------

SAMPLE_RULES = """\
default: alert

risk_weights:
  resource_type:
    aws_instance: 7
    aws_security_group: 9
    docker_container: 2
  action_type:
    delete: 10
    replace: 8
    update: 4
    create: 2
  env:
    prod: 10
    stage: 5
    dev: 2

require_approval:
  - aws_instance
  - aws_security_group

auto_reconcile:
  - docker_container

ignore:
  - aws_autoscaling_group
"""


def _make_plan_json(resources):
    """Build a minimal terraform show -json payload."""
    return {
        "resource_changes": resources,
    }


def _make_mock_run(plan_json, apply_success=True, verify_clean=True):
    """Factory for a mock ``subprocess.run`` that handles all terraform cmds.

    NOTE: detector, reconciler, and verifier all share the same subprocess
    module, so a single mock handles calls from all three components.

    We match on the terraform *sub-command* (the second element of cmd)
    rather than substring matching to avoid false positives from file paths.
    """

    def _mock_run(cmd, **kwargs):
        m = MagicMock()
        # cmd[0] = "terraform", cmd[1] = sub-command
        sub_cmd = cmd[1] if len(cmd) > 1 else ""

        if sub_cmd == "init":
            m.returncode = 0
            m.stdout = b"Terraform has been successfully initialized!"
            m.stderr = b""

        elif sub_cmd == "show":
            m.returncode = 0
            m.stdout = json.dumps(plan_json).encode()
            m.stderr = b""

        elif sub_cmd == "apply":
            m.returncode = 0 if apply_success else 1
            m.stdout = b"Apply complete!" if apply_success else b""
            m.stderr = b"" if apply_success else b"Error applying plan"

        elif sub_cmd == "plan":
            has_changes = len(plan_json.get("resource_changes", [])) > 0
            # Verification plan calls use verify.tfplan
            if any("verify.tfplan" in arg for arg in cmd):
                m.returncode = 0 if verify_clean else 2
            else:
                m.returncode = 2 if has_changes else 0

            m.stdout = b""
            m.stderr = b""

            # Create fake plan file so reconciler can find it
            cwd = kwargs.get("cwd", ".")
            for part in cmd:
                if part.endswith("tfplan"):
                    plan_path = os.path.join(cwd, os.path.basename(part))
                    os.makedirs(os.path.dirname(plan_path) if os.path.dirname(plan_path) else ".", exist_ok=True)
                    open(plan_path, "w").close()
        else:
            m.returncode = 0
            m.stdout = b""
            m.stderr = b""

        return m

    return _mock_run


@pytest.fixture
def workspace(tmp_path):
    """Create a temporary Terraform workspace with rules config."""
    tf_dir = tmp_path / "terraform"
    tf_dir.mkdir()
    (tf_dir / "main.tf").write_text('resource "docker_container" "demo" {}')

    rules_path = tmp_path / "rules.yml"
    rules_path.write_text(SAMPLE_RULES)

    db_path = tmp_path / "test.db"

    return {
        "tf_dir": str(tf_dir),
        "rules_path": str(rules_path),
        "db_url": f"sqlite:///{db_path}",
    }


# ===========================================================================
# Integration tests
# ===========================================================================


class TestPipelineIntegration:
    """End-to-end integration tests for the full pipeline.

    NOTE: detector, reconciler, and verifier all share the same ``subprocess``
    module object.  We therefore patch it once via ``subprocess.run``.
    """

    # ---------------------------------------------------------------
    # 1. No drift → empty result
    # ---------------------------------------------------------------
    @patch("subprocess.run")
    def test_no_drift_returns_empty_result(self, mock_run, workspace):
        """When Terraform reports no changes, the pipeline does nothing."""
        plan_json = _make_plan_json([])
        mock_run.side_effect = _make_mock_run(plan_json)

        pipeline = Pipeline(**workspace, dry_run=False)
        result = pipeline.run(skip_init=True)

        assert isinstance(result, PipelineResult)
        assert len(result.events) == 0
        assert result.reconciled == 0
        assert result.failed == 0

    # ---------------------------------------------------------------
    # 2. Auto-reconcile path (docker_container, dev env)
    # ---------------------------------------------------------------
    @patch("subprocess.run")
    def test_auto_reconcile_docker_container(self, mock_run, workspace):
        """docker_container in dev env should be auto-reconciled."""
        plan_json = _make_plan_json([{
            "address": "docker_container.demo",
            "type": "docker_container",
            "change": {
                "actions": ["update"],
                "before": {"name": "demo", "labels": {"env": "dev"}},
                "after": {"name": "demo_v2", "labels": {"env": "dev"}},
            },
        }])

        mock_run.side_effect = _make_mock_run(plan_json, apply_success=True, verify_clean=True)

        pipeline = Pipeline(**workspace, dry_run=False)
        result = pipeline.run(skip_init=True)

        assert len(result.events) == 1
        assert result.events[0]["decision"] == "reconcile"
        assert result.reconciled == 1
        assert result.failed == 0

        # Verify the event was persisted
        ev = pipeline.storage.get_event(result.events[0]["id"])
        assert ev is not None
        assert ev.status == "reconciled"

        # Verify audit trail exists
        audits = pipeline.storage.list_audit()
        actions = [a.action for a in audits]
        assert "detected" in actions
        assert "classified" in actions
        assert "decided" in actions
        assert "reconciled" in actions

    # ---------------------------------------------------------------
    # 3. Require-approval path (aws_security_group → manual)
    # ---------------------------------------------------------------
    @patch("subprocess.run")
    def test_require_approval_routes_to_manual(self, mock_run, workspace):
        """aws_security_group should always require manual approval."""
        plan_json = _make_plan_json([{
            "address": "aws_security_group.web",
            "type": "aws_security_group",
            "change": {
                "actions": ["update"],
                "before": {"ingress": []},
                "after": {"ingress": [{"from_port": 22}], "tags": {"env": "dev"}},
            },
        }])

        mock_run.side_effect = _make_mock_run(plan_json)

        pipeline = Pipeline(**workspace, dry_run=False)
        result = pipeline.run(skip_init=True)

        assert len(result.events) == 1
        assert result.events[0]["decision"] == "manual"
        assert result.manual == 1
        assert result.reconciled == 0

        # PR stub should have been created
        pr_path = os.path.join(workspace["tf_dir"], "pr_description.md")
        assert os.path.exists(pr_path)

    # ---------------------------------------------------------------
    # 4. Ignore path (aws_autoscaling_group)
    # ---------------------------------------------------------------
    @patch("subprocess.run")
    def test_ignored_resource_is_skipped(self, mock_run, workspace):
        """aws_autoscaling_group should be silently ignored."""
        plan_json = _make_plan_json([{
            "address": "aws_autoscaling_group.web",
            "type": "aws_autoscaling_group",
            "change": {
                "actions": ["update"],
                "before": {"desired_capacity": 2},
                "after": {"desired_capacity": 3, "tags": {"env": "prod"}},
            },
        }])

        mock_run.side_effect = _make_mock_run(plan_json)

        pipeline = Pipeline(**workspace, dry_run=False)
        result = pipeline.run(skip_init=True)

        assert len(result.events) == 1
        assert result.events[0]["decision"] == "ignore"
        assert result.ignored == 1

    # ---------------------------------------------------------------
    # 5. Production guard (docker_container in prod → manual)
    # ---------------------------------------------------------------
    @patch("subprocess.run")
    def test_prod_env_blocks_auto_apply(self, mock_run, workspace):
        """Even auto_reconcile resources should be blocked in prod."""
        plan_json = _make_plan_json([{
            "address": "docker_container.app",
            "type": "docker_container",
            "change": {
                "actions": ["update"],
                "before": {"name": "app", "labels": {"env": "prod"}},
                "after": {"name": "app_v2", "labels": {"env": "prod"}},
            },
        }])

        mock_run.side_effect = _make_mock_run(plan_json)

        pipeline = Pipeline(**workspace, dry_run=False, auto_apply_prod=False)
        result = pipeline.run(skip_init=True)

        assert len(result.events) == 1
        assert result.events[0]["decision"] == "manual"
        assert result.manual == 1

    # ---------------------------------------------------------------
    # 6. Failed reconciliation
    # ---------------------------------------------------------------
    @patch("subprocess.run")
    def test_failed_apply_marks_events_failed(self, mock_run, workspace):
        """When terraform apply fails, events should be marked failed."""
        plan_json = _make_plan_json([{
            "address": "docker_container.demo",
            "type": "docker_container",
            "change": {
                "actions": ["update"],
                "before": {"name": "demo", "labels": {"env": "dev"}},
                "after": {"name": "demo_v2", "labels": {"env": "dev"}},
            },
        }])

        mock_run.side_effect = _make_mock_run(plan_json, apply_success=False)

        pipeline = Pipeline(**workspace, dry_run=False)
        result = pipeline.run(skip_init=True)

        assert result.failed == 1
        assert result.reconciled == 0

        ev = pipeline.storage.get_event(result.events[0]["id"])
        assert ev.status == "failed"

    # ---------------------------------------------------------------
    # 7. Dry-run mode — nothing is actually applied
    # ---------------------------------------------------------------
    @patch("subprocess.run")
    def test_dry_run_does_not_apply(self, mock_run, workspace):
        """In dry-run mode, reconciler should not call terraform apply."""
        plan_json = _make_plan_json([{
            "address": "docker_container.demo",
            "type": "docker_container",
            "change": {
                "actions": ["update"],
                "before": {"name": "demo", "labels": {"env": "dev"}},
                "after": {"name": "demo_v2", "labels": {"env": "dev"}},
            },
        }])

        mock_run.side_effect = _make_mock_run(plan_json)

        pipeline = Pipeline(**workspace, dry_run=True)
        result = pipeline.run(skip_init=True)

        assert result.reconciled == 1
        assert result.failed == 0
        # In dry-run mode, the "apply" sub-command should never be called
        for call_args in mock_run.call_args_list:
            cmd = call_args[0][0]
            assert cmd[1] != "apply", "terraform apply should not be called in dry-run"

    # ---------------------------------------------------------------
    # 8. Multiple resources in a single plan (mixed decisions)
    # ---------------------------------------------------------------
    @patch("subprocess.run")
    def test_mixed_resources_different_decisions(self, mock_run, workspace):
        """A single plan with multiple resources should produce different decisions."""
        plan_json = _make_plan_json([
            {
                "address": "docker_container.app",
                "type": "docker_container",
                "change": {
                    "actions": ["update"],
                    "before": {"name": "app", "labels": {"env": "dev"}},
                    "after": {"name": "app_v2", "labels": {"env": "dev"}},
                },
            },
            {
                "address": "aws_security_group.web",
                "type": "aws_security_group",
                "change": {
                    "actions": ["update"],
                    "before": {"ingress": []},
                    "after": {"ingress": [{"from_port": 443}], "tags": {"env": "dev"}},
                },
            },
            {
                "address": "aws_autoscaling_group.workers",
                "type": "aws_autoscaling_group",
                "change": {
                    "actions": ["update"],
                    "before": {"desired_capacity": 1},
                    "after": {"desired_capacity": 3, "tags": {"env": "dev"}},
                },
            },
        ])

        mock_run.side_effect = _make_mock_run(plan_json, apply_success=True, verify_clean=True)

        pipeline = Pipeline(**workspace, dry_run=False)
        result = pipeline.run(skip_init=True)

        decisions = {ev["address"]: ev["decision"] for ev in result.events}
        assert decisions["docker_container.app"] == "reconcile"
        assert decisions["aws_security_group.web"] == "manual"
        assert decisions["aws_autoscaling_group.workers"] == "ignore"

        assert result.reconciled == 1
        assert result.manual == 1
        assert result.ignored == 1
        assert len(result.events) == 3

    # ---------------------------------------------------------------
    # 9. Metrics / counts are correct after pipeline run
    # ---------------------------------------------------------------
    @patch("subprocess.run")
    def test_storage_counts_match_result(self, mock_run, workspace):
        """Storage.counts() should match the PipelineResult after a run."""
        plan_json = _make_plan_json([
            {
                "address": "docker_container.app",
                "type": "docker_container",
                "change": {
                    "actions": ["update"],
                    "before": {"name": "app", "labels": {"env": "dev"}},
                    "after": {"name": "app_v2", "labels": {"env": "dev"}},
                },
            },
            {
                "address": "aws_instance.web",
                "type": "aws_instance",
                "change": {
                    "actions": ["update"],
                    "before": {"instance_type": "t2.micro"},
                    "after": {"instance_type": "t3.large", "tags": {"env": "stage"}},
                },
            },
        ])

        mock_run.side_effect = _make_mock_run(plan_json, apply_success=True, verify_clean=True)

        pipeline = Pipeline(**workspace, dry_run=False)
        result = pipeline.run(skip_init=True)

        counts = pipeline.storage.counts()
        assert counts["total"] == 2
        assert counts["reconciled"] == result.reconciled

    # ---------------------------------------------------------------
    # 10. Init is called when skip_init=False
    # ---------------------------------------------------------------
    @patch("subprocess.run")
    def test_init_is_called_by_default(self, mock_run, workspace):
        """terraform init should be invoked when skip_init=False."""
        plan_json = _make_plan_json([])
        mock_run.side_effect = _make_mock_run(plan_json)

        pipeline = Pipeline(**workspace, dry_run=False)
        result = pipeline.run(skip_init=False)

        # init call should be the first subprocess.run invocation
        first_call_args = mock_run.call_args_list[0][0][0]
        assert "init" in first_call_args
