"""Verifier – confirms infrastructure matches desired state after reconciliation.

Runs ``terraform plan -detailed-exitcode`` and expects exit code 0 (no changes).
"""

import logging
import os
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class VerifyResult:
    is_clean: bool
    message: str


class Verifier:
    """Re-runs Terraform plan to assert zero remaining drift."""

    def __init__(self, tf_dir: str, terraform_bin: str = "terraform"):
        self.tf_dir = os.path.abspath(tf_dir)
        self.terraform = terraform_bin

    def verify(self) -> VerifyResult:
        """Return ``VerifyResult(is_clean=True)`` when no diff remains."""
        plan_path = os.path.join(self.tf_dir, "verify.tfplan")

        res = subprocess.run(
            [self.terraform, "plan", "-detailed-exitcode", "-out", plan_path],
            cwd=self.tf_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        if res.returncode == 0:
            logger.info("Verification passed – no drift remaining")
            return VerifyResult(True, "No drift remaining")

        if res.returncode == 2:
            logger.warning("Verification failed – drift still present")
            return VerifyResult(False, "Drift still detected after reconciliation")

        err = res.stderr.decode()
        logger.error("Verification error:\n%s", err)
        return VerifyResult(False, f"terraform plan error: {err}")
