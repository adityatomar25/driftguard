"""Reconciler – safely restores infrastructure to desired state.

Supports two modes:
  • Auto-apply  – runs ``terraform apply`` with the saved plan.
  • PR creation – creates a stub PR description for human review (extend
                  with GitHub API integration as needed).
"""

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class ReconcileResult:
    success: bool
    mode: str          # "auto_apply" | "pr_created" | "dry_run"
    message: str


class Reconciler:
    """Applies Terraform plans or creates PR stubs for manual review."""

    def __init__(self, tf_dir: str, terraform_bin: str = "terraform", dry_run: bool = False):
        self.tf_dir = os.path.abspath(tf_dir)
        self.terraform = terraform_bin
        self.dry_run = dry_run
        self._plan_path = os.path.join(self.tf_dir, "tfplan")

    # ------------------------------------------------------------------
    # Auto-apply
    # ------------------------------------------------------------------

    def apply_plan(self) -> ReconcileResult:
        """Run ``terraform apply`` with the previously saved plan file."""
        if self.dry_run:
            logger.info("[DRY-RUN] Would apply plan at %s", self._plan_path)
            return ReconcileResult(True, "dry_run", "Dry-run mode – no changes applied")

        if not os.path.exists(self._plan_path):
            return ReconcileResult(False, "auto_apply", f"Plan file not found: {self._plan_path}")

        logger.info("Applying plan: %s", self._plan_path)
        res = subprocess.run(
            [self.terraform, "apply", "-input=false", "-auto-approve", self._plan_path],
            cwd=self.tf_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        output = res.stdout.decode() + "\n" + res.stderr.decode()

        if res.returncode != 0:
            logger.error("terraform apply failed:\n%s", output)
            return ReconcileResult(False, "auto_apply", output.strip())

        logger.info("terraform apply succeeded")
        return ReconcileResult(True, "auto_apply", output.strip())

    # ------------------------------------------------------------------
    # PR creation stub
    # ------------------------------------------------------------------

    def create_pr(self, event_summary: str = "") -> ReconcileResult:
        """Create a stub PR description for human review.

        In a real deployment you would call the GitHub/GitLab API here.
        """
        pr_body = (
            "## DriftGuard – Manual Reconciliation Required\n\n"
            f"**Summary:** {event_summary}\n\n"
            f"**Terraform directory:** `{self.tf_dir}`\n\n"
            "Please review the plan and approve to reconcile."
        )
        pr_path = os.path.join(self.tf_dir, "pr_description.md")
        with open(pr_path, "w") as fh:
            fh.write(pr_body)
        logger.info("PR description written to %s", pr_path)
        return ReconcileResult(True, "pr_created", f"PR stub written to {pr_path}")
