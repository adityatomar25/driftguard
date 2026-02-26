"""Decision engine – chooses action based on classification, risk, and environment.

Follows the Kubernetes controller pattern: a reconciliation loop that
continuously drives actual state towards desired state, with safety
gates for high-risk / production changes.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from driftguard.classifier import ClassificationResult
from driftguard.detector import ChangeEvent

logger = logging.getLogger(__name__)


# Configurable thresholds
HIGH_RISK_THRESHOLD = 6.0
PROD_ENVS = {"prod", "production"}


@dataclass
class Decision:
    action: str          # reconcile | manual | alert | ignore
    reason: str


class DecisionEngine:
    """Environment-aware decision engine with safety defaults."""

    def __init__(
        self,
        high_risk_threshold: float = HIGH_RISK_THRESHOLD,
        prod_envs: Optional[set] = None,
        auto_apply_prod: bool = False,
    ):
        self.high_risk_threshold = high_risk_threshold
        self.prod_envs = prod_envs or PROD_ENVS
        self.auto_apply_prod = auto_apply_prod

    def decide(self, event: ChangeEvent, result: ClassificationResult) -> Decision:
        cls = result.classification
        env = event.env.lower() if event.env else "unknown"
        is_prod = env in self.prod_envs

        # 1. Ignore
        if cls == "ignore":
            return Decision("ignore", "Classification is ignore")

        # 2. Require approval always → manual
        if cls == "require_approval":
            return Decision("manual", f"Resource type requires approval (risk={result.risk_score})")

        # 3. High risk → manual
        if result.risk_score >= self.high_risk_threshold:
            return Decision("manual", f"Risk score {result.risk_score} >= threshold {self.high_risk_threshold}")

        # 4. Production guard
        if is_prod and not self.auto_apply_prod:
            return Decision("manual", f"Production environment ({env}) – auto-apply disabled")

        # 5. Auto reconcile
        if cls == "auto_reconcile":
            return Decision("reconcile", f"Auto-reconcile for {env} env (risk={result.risk_score})")

        # 6. Default → alert
        return Decision("alert", f"Default action for classification={cls}")
