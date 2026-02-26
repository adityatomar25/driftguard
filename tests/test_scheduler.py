"""Tests for the DriftGuard scheduler module."""

import json
import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from driftguard.scheduler import DriftScheduler
from driftguard.pipeline import PipelineResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_RULES = """\
default: alert
risk_weights:
  resource_type:
    docker_container: 2
  action_type:
    update: 4
  env:
    dev: 2
auto_reconcile:
  - docker_container
ignore: []
require_approval: []
"""


def _make_mock_run(has_changes=True, apply_ok=True):
    """Create a subprocess.run mock for terraform commands.

    Matches on the terraform sub-command (cmd[1]) to avoid false
    positives from file paths that may contain words like 'apply'.
    """
    plan_json = {
        "resource_changes": [
            {
                "address": "docker_container.demo",
                "type": "docker_container",
                "change": {
                    "actions": ["update"],
                    "before": {"name": "demo", "labels": {"env": "dev"}},
                    "after": {"name": "demo_v2", "labels": {"env": "dev"}},
                },
            },
        ] if has_changes else [],
    }

    def _mock(cmd, **kwargs):
        m = MagicMock()
        sub_cmd = cmd[1] if len(cmd) > 1 else ""

        if sub_cmd == "init":
            m.returncode = 0
            m.stdout = b"Initialized"
            m.stderr = b""
        elif sub_cmd == "show":
            m.returncode = 0
            m.stdout = json.dumps(plan_json).encode()
            m.stderr = b""
        elif sub_cmd == "apply":
            m.returncode = 0 if apply_ok else 1
            m.stdout = b"Apply complete!" if apply_ok else b""
            m.stderr = b"" if apply_ok else b"Error"
        elif sub_cmd == "plan":
            if any("verify.tfplan" in arg for arg in cmd):
                m.returncode = 0
            else:
                m.returncode = 2 if has_changes else 0
            m.stdout = b""
            m.stderr = b""
            # create fake plan file
            cwd = kwargs.get("cwd", ".")
            for part in cmd:
                if part.endswith("tfplan"):
                    path = os.path.join(cwd, os.path.basename(part))
                    open(path, "w").close()
        else:
            m.returncode = 0
            m.stdout = b""
            m.stderr = b""
        return m

    return _mock


@pytest.fixture
def sched_workspace(tmp_path):
    """Create a temp workspace for scheduler tests."""
    tf_dir = tmp_path / "terraform"
    tf_dir.mkdir()
    (tf_dir / "main.tf").write_text('resource "docker_container" "demo" {}')

    rules = tmp_path / "rules.yml"
    rules.write_text(SAMPLE_RULES)

    db_path = tmp_path / "sched_test.db"

    return {
        "tf_dir": str(tf_dir),
        "rules_path": str(rules),
        "db_url": f"sqlite:///{db_path}",
    }


# ===========================================================================
# Tests
# ===========================================================================


class TestDriftScheduler:
    """Unit tests for the DriftScheduler."""

    # ---------------------------------------------------------------
    # 1. run_once executes exactly one pipeline cycle
    # ---------------------------------------------------------------
    @patch("subprocess.run")
    def test_run_once(self, mock_run, sched_workspace):
        mock_run.side_effect = _make_mock_run(has_changes=True, apply_ok=True)

        sched = DriftScheduler(**sched_workspace, skip_init=True)
        result = sched.run_once()

        assert isinstance(result, PipelineResult)
        assert sched.run_count == 1
        assert sched.last_result is result

    # ---------------------------------------------------------------
    # 2. run_once with no drift
    # ---------------------------------------------------------------
    @patch("subprocess.run")
    def test_run_once_no_drift(self, mock_run, sched_workspace):
        mock_run.side_effect = _make_mock_run(has_changes=False)

        sched = DriftScheduler(**sched_workspace, skip_init=True)
        result = sched.run_once()

        assert len(result.events) == 0
        assert sched.run_count == 1

    # ---------------------------------------------------------------
    # 3. max_runs stops the loop
    # ---------------------------------------------------------------
    @patch("subprocess.run")
    def test_max_runs_limits_execution(self, mock_run, sched_workspace):
        mock_run.side_effect = _make_mock_run(has_changes=False)

        sched = DriftScheduler(**sched_workspace, skip_init=True)
        sched.start(interval_seconds=1, max_runs=3)

        assert sched.run_count == 3

    # ---------------------------------------------------------------
    # 4. stop() terminates the loop
    # ---------------------------------------------------------------
    @patch("subprocess.run")
    def test_stop_terminates_loop(self, mock_run, sched_workspace):
        mock_run.side_effect = _make_mock_run(has_changes=False)

        sched = DriftScheduler(**sched_workspace, skip_init=True)

        # Start scheduler in a background thread
        t = threading.Thread(target=sched.start, kwargs={"interval_seconds": 60})
        t.daemon = True
        t.start()

        # Give it time to complete the first run
        time.sleep(2)
        assert sched.run_count >= 1
        assert sched.is_running

        # Signal stop and wait for thread to finish
        sched.stop()
        t.join(timeout=5)

        assert not sched.is_running

    # ---------------------------------------------------------------
    # 5. Pipeline error does not crash the scheduler
    # ---------------------------------------------------------------
    @patch("subprocess.run")
    def test_error_does_not_crash_scheduler(self, mock_run, sched_workspace):
        """If the pipeline throws, the scheduler catches it and continues."""
        mock_run.side_effect = RuntimeError("Terraform binary not found")

        sched = DriftScheduler(**sched_workspace, skip_init=True)
        sched.start(interval_seconds=1, max_runs=2)

        # Should complete 2 runs even with errors
        assert sched.run_count == 2
        assert sched.last_result is not None
        assert len(sched.last_result.events) == 0

    # ---------------------------------------------------------------
    # 6. Properties are correct initially
    # ---------------------------------------------------------------
    def test_initial_state(self, sched_workspace):
        sched = DriftScheduler(**sched_workspace, skip_init=True)

        assert sched.run_count == 0
        assert sched.last_result is None
        assert sched.is_running  # not stopped yet
