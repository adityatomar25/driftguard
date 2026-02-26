"""Unit tests for DriftGuard classifier module."""

import os
import tempfile
import yaml
import pytest

from driftguard.classifier import Classifier, ClassificationResult
from driftguard.detector import ChangeEvent


SAMPLE_RULES = {
    "default": "alert",
    "risk_weights": {
        "resource_type": {"aws_instance": 7, "docker_container": 2},
        "action_type": {"delete": 10, "update": 4, "create": 2},
        "env": {"prod": 10, "dev": 2},
    },
    "require_approval": ["aws_instance", "aws_security_group"],
    "auto_reconcile": ["docker_container"],
    "ignore": ["aws_autoscaling_group"],
}


@pytest.fixture
def rules_file(tmp_path):
    path = tmp_path / "rules.yml"
    path.write_text(yaml.dump(SAMPLE_RULES))
    return str(path)


class TestClassifier:
    def test_auto_reconcile(self, rules_file):
        classifier = Classifier(rules_file)
        event = ChangeEvent(address="docker_container.demo", resource_type="docker_container", actions=["update"], env="dev")
        result = classifier.classify(event)
        assert result.classification == "auto_reconcile"

    def test_require_approval(self, rules_file):
        classifier = Classifier(rules_file)
        event = ChangeEvent(address="aws_instance.web", resource_type="aws_instance", actions=["update"], env="prod")
        result = classifier.classify(event)
        assert result.classification == "require_approval"

    def test_ignore(self, rules_file):
        classifier = Classifier(rules_file)
        event = ChangeEvent(address="aws_autoscaling_group.asg", resource_type="aws_autoscaling_group", actions=["update"], env="prod")
        result = classifier.classify(event)
        assert result.classification == "ignore"
        assert result.risk_score == 0.0

    def test_default_alert(self, rules_file):
        classifier = Classifier(rules_file)
        event = ChangeEvent(address="aws_lambda.fn", resource_type="aws_lambda_function", actions=["update"], env="dev")
        result = classifier.classify(event)
        assert result.classification == "alert"

    def test_risk_scoring(self, rules_file):
        classifier = Classifier(rules_file)
        event = ChangeEvent(address="aws_instance.web", resource_type="aws_instance", actions=["delete"], env="prod")
        result = classifier.classify(event)
        # High risk: aws_instance(7) + delete(10) + prod(10) = 27, normalised = min(27/3, 10) = 9.0
        assert result.risk_score == 9.0

    def test_classification_result_has_reasons(self, rules_file):
        classifier = Classifier(rules_file)
        event = ChangeEvent(address="docker_container.demo", resource_type="docker_container", actions=["update"], env="dev")
        result = classifier.classify(event)
        assert isinstance(result.reasons, list)
        assert len(result.reasons) > 0
