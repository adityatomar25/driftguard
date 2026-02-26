"""Drift detector – runs Terraform plan and parses JSON output.

Uses ``terraform plan -detailed-exitcode`` semantics:
  0 → no changes   2 → changes detected   1 → error

The parsed plan JSON is used to extract per-resource change events.
"""

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ChangeEvent:
    """Normalized representation of a single resource drift."""

    address: str
    resource_type: str
    actions: List[str]
    before: Optional[Dict[str, Any]] = None
    after: Optional[Dict[str, Any]] = None
    env: str = "unknown"
    diff_summary: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class TerraformDetector:
    """Wraps Terraform CLI to detect infrastructure drift."""

    def __init__(self, tf_dir: str, terraform_bin: str = "terraform"):
        self.tf_dir = os.path.abspath(tf_dir)
        self.terraform = terraform_bin
        self._plan_path = os.path.join(self.tf_dir, "tfplan")

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _run(self, args: List[str], check: bool = False) -> subprocess.CompletedProcess:
        cmd = [self.terraform] + args
        logger.debug("Running: %s  cwd=%s", " ".join(cmd), self.tf_dir)
        return subprocess.run(
            cmd, cwd=self.tf_dir,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=check,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init(self) -> None:
        """Run ``terraform init``."""
        res = self._run(["init", "-input=false"], check=False)
        if res.returncode != 0:
            raise RuntimeError(f"terraform init failed:\n{res.stderr.decode()}")
        logger.info("terraform init succeeded in %s", self.tf_dir)

    def plan(self) -> Dict[str, Any]:
        """Run ``terraform plan`` and return the JSON representation."""
        res = self._run(["plan", "-detailed-exitcode", "-out", self._plan_path])

        if res.returncode == 1:
            raise RuntimeError(f"terraform plan error:\n{res.stderr.decode()}")

        has_changes = res.returncode == 2
        logger.info("terraform plan exit=%d  has_changes=%s", res.returncode, has_changes)

        show = self._run(["show", "-json", self._plan_path], check=True)
        return json.loads(show.stdout)

    def detect(self) -> List[ChangeEvent]:
        """Detect drift and return a list of ``ChangeEvent`` objects."""
        plan_json = self.plan()
        events: List[ChangeEvent] = []

        for rc in plan_json.get("resource_changes", []):
            change = rc.get("change", {})
            actions = change.get("actions", [])

            if actions == ["no-op"]:
                continue

            after = change.get("after") or {}
            # Try to extract env tag
            env = "unknown"
            for tag_field in ("tags", "labels"):
                tags = after.get(tag_field, {}) or {}
                if isinstance(tags, dict) and "env" in tags:
                    env = tags["env"]
                    break

            diff_lines = []
            before = change.get("before") or {}
            if isinstance(before, dict) and isinstance(after, dict):
                all_keys = set(list(before.keys()) + list(after.keys()))
                for k in sorted(all_keys):
                    bv, av = before.get(k), after.get(k)
                    if bv != av:
                        diff_lines.append(f"  {k}: {bv!r} → {av!r}")

            events.append(ChangeEvent(
                address=rc.get("address", "unknown"),
                resource_type=rc.get("type", "unknown"),
                actions=actions,
                before=before if before else None,
                after=after if after else None,
                env=env,
                diff_summary="\n".join(diff_lines),
            ))

        logger.info("Detected %d drift event(s)", len(events))
        return events
