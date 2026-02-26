"""Unit tests for DriftGuard decision engine."""

import pytest

from driftguard.classifier import ClassificationResult
from driftguard.decision import DecisionEngine, Decision
from driftguard.detector import ChangeEvent


class TestDecisionEngine:
    def setup_method(self):
        self.engine = DecisionEngine(high_risk_threshold=6.0, auto_apply_prod=False)

    def _event(self, env="dev"):
        return ChangeEvent(address="test.resource", resource_type="docker_container", actions=["update"], env=env)

    def test_auto_reconcile_non_prod(self):
        result = ClassificationResult("auto_reconcile", 3.0, ["test"])
        decision = self.engine.decide(self._event("dev"), result)
        assert decision.action == "reconcile"

    def test_prod_blocked_by_default(self):
        result = ClassificationResult("auto_reconcile", 3.0, ["test"])
        decision = self.engine.decide(self._event("prod"), result)
        assert decision.action == "manual"

    def test_prod_allowed_when_enabled(self):
        engine = DecisionEngine(auto_apply_prod=True)
        result = ClassificationResult("auto_reconcile", 3.0, ["test"])
        decision = engine.decide(self._event("prod"), result)
        assert decision.action == "reconcile"

    def test_require_approval_always_manual(self):
        result = ClassificationResult("require_approval", 8.0, ["test"])
        decision = self.engine.decide(self._event("dev"), result)
        assert decision.action == "manual"

    def test_high_risk_triggers_manual(self):
        result = ClassificationResult("auto_reconcile", 7.5, ["test"])
        decision = self.engine.decide(self._event("dev"), result)
        assert decision.action == "manual"

    def test_ignore_stays_ignored(self):
        result = ClassificationResult("ignore", 0.0, ["test"])
        decision = self.engine.decide(self._event("dev"), result)
        assert decision.action == "ignore"

    def test_default_alert(self):
        result = ClassificationResult("alert", 2.0, ["test"])
        decision = self.engine.decide(self._event("dev"), result)
        assert decision.action == "alert"
