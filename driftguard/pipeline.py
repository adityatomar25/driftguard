"""Pipeline – orchestrates the full detect → classify → decide → reconcile → verify loop."""

import logging
from typing import List, Optional

from driftguard.classifier import Classifier, ClassificationResult
from driftguard.decision import Decision, DecisionEngine
from driftguard.detector import ChangeEvent, TerraformDetector
from driftguard.reconciler import ReconcileResult, Reconciler
from driftguard.storage import Storage
from driftguard.verifier import Verifier, VerifyResult

logger = logging.getLogger(__name__)


class PipelineResult:
    def __init__(self):
        self.events: List[dict] = []
        self.reconciled: int = 0
        self.failed: int = 0
        self.manual: int = 0
        self.ignored: int = 0
        self.alerted: int = 0


class Pipeline:
    """Closed-loop drift detection and reconciliation pipeline."""

    def __init__(
        self,
        tf_dir: str,
        rules_path: str,
        db_url: str = "sqlite:///driftguard.db",
        dry_run: bool = False,
        auto_apply_prod: bool = False,
    ):
        self.detector = TerraformDetector(tf_dir)
        self.classifier = Classifier(rules_path)
        self.decision_engine = DecisionEngine(auto_apply_prod=auto_apply_prod)
        self.reconciler = Reconciler(tf_dir, dry_run=dry_run)
        self.verifier = Verifier(tf_dir)
        self.storage = Storage(db_url)

    def run(self, skip_init: bool = False) -> PipelineResult:
        """Execute one full detection-and-reconciliation cycle."""
        result = PipelineResult()

        # 1. Init (optional)
        if not skip_init:
            self.detector.init()

        # 2. Detect
        change_events: List[ChangeEvent] = self.detector.detect()
        if not change_events:
            logger.info("No drift detected – infrastructure is in desired state")
            return result

        needs_reconcile = False

        for event in change_events:
            # 3. Classify
            classification: ClassificationResult = self.classifier.classify(event)

            # 4. Decide
            decision: Decision = self.decision_engine.decide(event, classification)

            # 5. Persist event
            saved = self.storage.save_event({
                "terraform_address": event.address,
                "resource_type": event.resource_type,
                "env": event.env,
                "actions": event.actions,
                "before": event.before,
                "after": event.after,
                "diff_summary": event.diff_summary,
                "classification": classification.classification,
                "risk_score": classification.risk_score,
                "decision": decision.action,
                "status": "detected",
            })
            self.storage.log_audit("detected", saved.id, f"actions={event.actions}")
            self.storage.log_audit("classified", saved.id, f"{classification.classification} risk={classification.risk_score}")
            self.storage.log_audit("decided", saved.id, decision.reason)

            event_summary = {
                "id": saved.id,
                "address": event.address,
                "classification": classification.classification,
                "risk_score": classification.risk_score,
                "decision": decision.action,
                "reason": decision.reason,
            }
            result.events.append(event_summary)

            # 6. Act
            if decision.action == "reconcile":
                needs_reconcile = True
            elif decision.action == "manual":
                self.reconciler.create_pr(event.diff_summary)
                self.storage.update_event(saved.id, status="pending")
                self.storage.log_audit("pr_created", saved.id, "Manual review requested")
                result.manual += 1
            elif decision.action == "ignore":
                self.storage.update_event(saved.id, status="ignored")
                result.ignored += 1
            else:
                self.storage.update_event(saved.id, status="alerted")
                result.alerted += 1

        # 7. Reconcile (once for all auto-reconcile events in the same plan)
        if needs_reconcile:
            rec: ReconcileResult = self.reconciler.apply_plan()
            for ev in result.events:
                if ev["decision"] == "reconcile":
                    if rec.success:
                        self.storage.update_event(ev["id"], status="reconciled", reconciler_output=rec.message)
                        self.storage.log_audit("reconciled", ev["id"], rec.message[:500])
                        result.reconciled += 1
                    else:
                        self.storage.update_event(ev["id"], status="failed", reconciler_output=rec.message)
                        self.storage.log_audit("failed", ev["id"], rec.message[:500])
                        result.failed += 1

            # 8. Verify
            if rec.success:
                vr: VerifyResult = self.verifier.verify()
                if not vr.is_clean:
                    logger.warning("Post-reconciliation verification failed: %s", vr.message)
                else:
                    logger.info("Post-reconciliation verification passed")

        logger.info(
            "Pipeline complete: %d event(s), %d reconciled, %d manual, %d alerted, %d ignored, %d failed",
            len(result.events), result.reconciled, result.manual, result.alerted, result.ignored, result.failed,
        )
        return result
