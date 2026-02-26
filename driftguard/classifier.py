"""Rule-based drift classifier with risk scoring.

Rules are loaded from a YAML file with the structure::

    default: alert
    risk_weights:
      resource_type:
        aws_security_group: 9
        aws_instance: 7
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
      - aws_db_instance
    auto_reconcile:
      - docker_container
      - aws_s3_bucket_object
    ignore:
      - aws_autoscaling_group
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List

import yaml

from driftguard.detector import ChangeEvent

logger = logging.getLogger(__name__)


@dataclass
class ClassificationResult:
    classification: str        # auto_reconcile | require_approval | alert | ignore
    risk_score: float          # 0‑10
    reasons: List[str]


class Classifier:
    """Classifies drift events using YAML rule definitions."""

    def __init__(self, rules_path: str):
        with open(rules_path, "r") as fh:
            self.rules: Dict[str, Any] = yaml.safe_load(fh) or {}
        self._risk_weights = self.rules.get("risk_weights", {})
        logger.info("Loaded classifier rules from %s", rules_path)

    # ------------------------------------------------------------------

    def _compute_risk(self, event: ChangeEvent) -> float:
        score = 0.0
        reasons: List[str] = []

        # Resource type weight
        rt_weights = self._risk_weights.get("resource_type", {})
        if event.resource_type in rt_weights:
            w = rt_weights[event.resource_type]
            score += w
            reasons.append(f"resource_type={event.resource_type} (+{w})")

        # Action type weight (take the heaviest action)
        act_weights = self._risk_weights.get("action_type", {})
        for action in event.actions:
            if action in act_weights:
                w = act_weights[action]
                score += w
                reasons.append(f"action={action} (+{w})")

        # Environment weight
        env_weights = self._risk_weights.get("env", {})
        if event.env in env_weights:
            w = env_weights[event.env]
            score += w
            reasons.append(f"env={event.env} (+{w})")

        # Normalise to 0‑10
        score = min(score / 3.0, 10.0)
        return round(score, 2), reasons

    # ------------------------------------------------------------------

    def classify(self, event: ChangeEvent) -> ClassificationResult:
        """Classify a single ``ChangeEvent``."""
        rtype = event.resource_type

        # Check ignore list first
        for pattern in self.rules.get("ignore", []):
            if rtype == pattern or rtype.endswith(pattern):
                return ClassificationResult("ignore", 0.0, [f"matched ignore rule: {pattern}"])

        risk_score, reasons = self._compute_risk(event)

        # Check require_approval
        for pattern in self.rules.get("require_approval", []):
            if rtype == pattern or rtype.endswith(pattern):
                return ClassificationResult("require_approval", risk_score, reasons + [f"matched require_approval: {pattern}"])

        # Check auto_reconcile
        for pattern in self.rules.get("auto_reconcile", []):
            if rtype == pattern or rtype.endswith(pattern):
                return ClassificationResult("auto_reconcile", risk_score, reasons + [f"matched auto_reconcile: {pattern}"])

        default = self.rules.get("default", "alert")
        return ClassificationResult(default, risk_score, reasons + ["default rule applied"])
