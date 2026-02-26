"""Unit tests for DriftGuard detector module."""

import json
from unittest.mock import MagicMock, patch
import subprocess
import pytest

from driftguard.detector import TerraformDetector, ChangeEvent


# Sample terraform show -json output
SAMPLE_PLAN_JSON = {
    "resource_changes": [
        {
            "address": "docker_container.demo",
            "type": "docker_container",
            "change": {
                "actions": ["update"],
                "before": {"name": "driftguard_demo", "env": ["ENV=dev"], "labels": {"env": "dev"}},
                "after": {"name": "driftguard_demo", "env": ["ENV=staging"], "labels": {"env": "dev"}},
            }
        },
        {
            "address": "docker_image.nginx",
            "type": "docker_image",
            "change": {
                "actions": ["no-op"],
                "before": {"name": "nginx:alpine"},
                "after": {"name": "nginx:alpine"},
            }
        },
    ]
}


def _mock_run(cmd, **kwargs):
    """Mock subprocess.run for terraform commands."""
    mock = MagicMock()
    if "plan" in cmd:
        mock.returncode = 2  # changes detected
        mock.stdout = b""
        mock.stderr = b""
    elif "show" in cmd:
        mock.returncode = 0
        mock.stdout = json.dumps(SAMPLE_PLAN_JSON).encode()
        mock.stderr = b""
    elif "init" in cmd:
        mock.returncode = 0
        mock.stdout = b"Initialized"
        mock.stderr = b""
    else:
        mock.returncode = 0
        mock.stdout = b""
        mock.stderr = b""
    return mock


class TestTerraformDetector:
    @patch("driftguard.detector.subprocess.run", side_effect=_mock_run)
    def test_detect_finds_changes(self, mock_run):
        detector = TerraformDetector("/tmp/test-tf")
        events = detector.detect()

        assert len(events) == 1
        assert events[0].address == "docker_container.demo"
        assert events[0].resource_type == "docker_container"
        assert events[0].actions == ["update"]

    @patch("driftguard.detector.subprocess.run", side_effect=_mock_run)
    def test_detect_skips_noop(self, mock_run):
        detector = TerraformDetector("/tmp/test-tf")
        events = detector.detect()

        addresses = [e.address for e in events]
        assert "docker_image.nginx" not in addresses

    @patch("driftguard.detector.subprocess.run", side_effect=_mock_run)
    def test_detect_extracts_env(self, mock_run):
        detector = TerraformDetector("/tmp/test-tf")
        events = detector.detect()

        assert events[0].env == "dev"

    @patch("driftguard.detector.subprocess.run", side_effect=_mock_run)
    def test_init(self, mock_run):
        detector = TerraformDetector("/tmp/test-tf")
        detector.init()
        # init should call terraform init
        mock_run.assert_called()

    @patch("driftguard.detector.subprocess.run")
    def test_plan_error(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr=b"Error: something went wrong", stdout=b"")
        detector = TerraformDetector("/tmp/test-tf")
        with pytest.raises(RuntimeError, match="terraform plan error"):
            detector.plan()

    def test_change_event_to_dict(self):
        ev = ChangeEvent(
            address="test.resource",
            resource_type="aws_instance",
            actions=["update"],
            env="prod",
        )
        d = ev.to_dict()
        assert d["address"] == "test.resource"
        assert d["resource_type"] == "aws_instance"
        assert d["env"] == "prod"
