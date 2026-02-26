"""Alerting module – sends notifications via Slack webhook or console."""

import json
import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


class Alerter:
    """Dispatches alerts to configured channels."""

    def __init__(self, slack_webhook_url: Optional[str] = None):
        self.slack_url = slack_webhook_url or os.environ.get("DRIFTGUARD_SLACK_WEBHOOK")

    def send(self, title: str, message: str, severity: str = "info", payload: Optional[Dict[str, Any]] = None):
        """Send an alert to all configured channels."""
        self._log_alert(title, message, severity)

        if self.slack_url:
            self._send_slack(title, message, severity)

    def _log_alert(self, title: str, message: str, severity: str):
        log_fn = logger.warning if severity in ("high", "critical") else logger.info
        log_fn("[ALERT:%s] %s – %s", severity.upper(), title, message)

    def _send_slack(self, title: str, message: str, severity: str):
        if not _HAS_REQUESTS:
            logger.warning("requests library not installed – skipping Slack alert")
            return

        color_map = {"critical": "#FF0000", "high": "#FF6600", "info": "#36A64F", "low": "#CCCCCC"}
        color = color_map.get(severity, "#CCCCCC")

        slack_payload = {
            "attachments": [{
                "color": color,
                "title": f"🔔 DriftGuard: {title}",
                "text": message,
                "footer": "DriftGuard Alerting",
            }]
        }
        try:
            resp = requests.post(self.slack_url, json=slack_payload, timeout=10)
            resp.raise_for_status()
            logger.info("Slack alert sent")
        except Exception as exc:
            logger.error("Failed to send Slack alert: %s", exc)
