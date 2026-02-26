"""CLI entry point for DriftGuard pipeline."""

import argparse
import logging
import sys

from driftguard.pipeline import Pipeline


def main():
    parser = argparse.ArgumentParser(description="DriftGuard – Infrastructure Drift Detection & Reconciliation")
    parser.add_argument("--tf-dir", required=True, help="Path to the Terraform working directory")
    parser.add_argument("--rules", default="driftguard/config.yml", help="Path to classification rules YAML")
    parser.add_argument("--db", default="sqlite:///driftguard.db", help="Database URL")
    parser.add_argument("--dry-run", action="store_true", help="Preview actions without applying changes")
    parser.add_argument("--auto-apply-prod", action="store_true", help="Allow auto-apply in production (dangerous)")
    parser.add_argument("--skip-init", action="store_true", help="Skip terraform init")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    )

    pipeline = Pipeline(
        tf_dir=args.tf_dir,
        rules_path=args.rules,
        db_url=args.db,
        dry_run=args.dry_run,
        auto_apply_prod=args.auto_apply_prod,
    )

    result = pipeline.run(skip_init=args.skip_init)

    # Print summary
    print("\n" + "=" * 60)
    print("DriftGuard Pipeline Summary")
    print("=" * 60)
    print(f"  Events detected : {len(result.events)}")
    print(f"  Reconciled      : {result.reconciled}")
    print(f"  Manual review   : {result.manual}")
    print(f"  Alerted         : {result.alerted}")
    print(f"  Ignored         : {result.ignored}")
    print(f"  Failed          : {result.failed}")
    print("=" * 60)

    if result.events:
        print("\nEvents:")
        for ev in result.events:
            print(f"  [{ev['decision']:>10}] {ev['address']}  "
                  f"(class={ev['classification']}, risk={ev['risk_score']})")

    sys.exit(1 if result.failed > 0 else 0)


if __name__ == "__main__":
    main()
