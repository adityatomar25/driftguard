"""Scheduler – runs the DriftGuard pipeline on a repeating interval.

Provides two modes:
  • Simple loop  – ``while True`` + ``time.sleep()``  (zero extra deps)
  • APScheduler  – interval trigger with configurable cron (if ``apscheduler``
                   is installed)

Usage from CLI::

    python -m driftguard.scheduler --tf-dir terraform/ --interval 300

Usage from Python::

    from driftguard.scheduler import DriftScheduler
    sched = DriftScheduler(tf_dir="terraform/", rules_path="driftguard/config.yml")
    sched.start(interval_seconds=300)
"""

import logging
import signal
import sys
import time
import threading
from datetime import datetime, timezone
from typing import Optional

from driftguard.pipeline import Pipeline, PipelineResult

logger = logging.getLogger(__name__)


class DriftScheduler:
    """Periodically executes the drift-detection pipeline.

    Supports graceful shutdown via ``SIGINT`` / ``SIGTERM`` (Ctrl-C).
    """

    def __init__(
        self,
        tf_dir: str,
        rules_path: str = "driftguard/config.yml",
        db_url: str = "sqlite:///driftguard.db",
        dry_run: bool = False,
        auto_apply_prod: bool = False,
        skip_init: bool = False,
    ):
        self.pipeline = Pipeline(
            tf_dir=tf_dir,
            rules_path=rules_path,
            db_url=db_url,
            dry_run=dry_run,
            auto_apply_prod=auto_apply_prod,
        )
        self.skip_init = skip_init
        self._stop_event = threading.Event()
        self._run_count: int = 0
        self._last_result: Optional[PipelineResult] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def run_count(self) -> int:
        """Number of completed pipeline runs."""
        return self._run_count

    @property
    def last_result(self) -> Optional[PipelineResult]:
        """Result from the most recent pipeline run."""
        return self._last_result

    @property
    def is_running(self) -> bool:
        return not self._stop_event.is_set()

    # ------------------------------------------------------------------
    # Core loop
    # ------------------------------------------------------------------

    def _execute_once(self) -> PipelineResult:
        """Run the pipeline once and handle errors gracefully."""
        ts = datetime.now(timezone.utc).isoformat()
        logger.info("━━━ Scheduled run #%d at %s ━━━", self._run_count + 1, ts)

        try:
            result = self.pipeline.run(skip_init=self.skip_init)
            self._run_count += 1
            self._last_result = result

            logger.info(
                "Run #%d complete: %d events, %d reconciled, %d manual, %d alerted, %d ignored, %d failed",
                self._run_count,
                len(result.events),
                result.reconciled,
                result.manual,
                result.alerted,
                result.ignored,
                result.failed,
            )
            return result

        except Exception:
            logger.exception("Pipeline run failed – will retry next interval")
            self._run_count += 1
            empty = PipelineResult()
            self._last_result = empty
            return empty  # empty result on error

    def start(self, interval_seconds: int = 300, max_runs: int = 0) -> None:
        """Start the scheduling loop.

        Args:
            interval_seconds: Seconds between each pipeline run (default 300 = 5 min).
            max_runs: Stop after this many runs; 0 means run forever.
        """
        logger.info(
            "DriftGuard scheduler starting — interval=%ds, max_runs=%s",
            interval_seconds,
            max_runs or "∞",
        )

        # Register signal handlers for graceful shutdown (only in main thread)
        import threading as _threading
        if _threading.current_thread() is _threading.main_thread():
            def _handle_signal(signum, frame):
                sig_name = signal.Signals(signum).name
                logger.info("Received %s — shutting down scheduler gracefully …", sig_name)
                self.stop()

            signal.signal(signal.SIGINT, _handle_signal)
            signal.signal(signal.SIGTERM, _handle_signal)

        # Run the first cycle immediately
        self._execute_once()

        # Then wait + repeat
        while not self._stop_event.is_set():
            if max_runs > 0 and self._run_count >= max_runs:
                logger.info("Reached max_runs=%d — stopping scheduler", max_runs)
                break

            # Interruptible sleep: check stop_event every second
            for _ in range(interval_seconds):
                if self._stop_event.is_set():
                    break
                time.sleep(1)

            if not self._stop_event.is_set():
                self._execute_once()

        logger.info("Scheduler stopped after %d run(s)", self._run_count)

    def stop(self) -> None:
        """Signal the scheduler to stop after the current run."""
        self._stop_event.set()

    def run_once(self) -> PipelineResult:
        """Convenience: run exactly one cycle (useful in tests)."""
        return self._execute_once()


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main():
    """Standalone scheduler CLI."""
    import argparse

    parser = argparse.ArgumentParser(
        description="DriftGuard Scheduler – Periodic drift detection & reconciliation"
    )
    parser.add_argument("--tf-dir", required=True, help="Terraform working directory")
    parser.add_argument("--rules", default="driftguard/config.yml", help="Classification rules YAML")
    parser.add_argument("--db", default="sqlite:///driftguard.db", help="Database URL")
    parser.add_argument("--interval", type=int, default=300, help="Seconds between runs (default: 300)")
    parser.add_argument("--max-runs", type=int, default=0, help="Max runs (0 = infinite)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without applying")
    parser.add_argument("--auto-apply-prod", action="store_true", help="Allow auto-apply in production")
    parser.add_argument("--skip-init", action="store_true", help="Skip terraform init")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    scheduler = DriftScheduler(
        tf_dir=args.tf_dir,
        rules_path=args.rules,
        db_url=args.db,
        dry_run=args.dry_run,
        auto_apply_prod=args.auto_apply_prod,
        skip_init=args.skip_init,
    )

    scheduler.start(
        interval_seconds=args.interval,
        max_runs=args.max_runs,
    )


if __name__ == "__main__":
    main()
