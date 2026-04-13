#!/usr/bin/env python3
"""Architecture validation coordinator with auto-refresh of runtime snapshot.

This script ensures the persisted runtime snapshot is fresh before running
architecture checks. If the snapshot is missing or stale (catalog changed),
it triggers the official bootstrap path to regenerate it.

Separation of responsibilities:
- This script: orchestrates detection, refresh, and verification
- check_architecture.py: pure verifier, no side effects
- runtime_snapshot.py: pure persistence, no side effects
- BootstrapContainer.create(): official bootstrap path that persists snapshot
"""

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def _snapshot_exists_and_fresh() -> bool:
    """Check if a valid runtime snapshot exists.

    Returns True only if the snapshot file exists and its catalog_hash
    matches the current catalog state.
    """
    from aioa.catalog.runtime_snapshot import load_persisted_runtime_snapshot
    return load_persisted_runtime_snapshot() is not None


def _refresh_snapshot_via_official_bootstrap() -> bool:
    """Execute the official bootstrap path to regenerate the runtime snapshot.

    Uses BootstrapContainer.create() which:
    1. Loads and validates the catalog
    2. Registers components via gatekeeper
    3. Validates runtime contract
    4. Validates wiring alignment
    5. Persists the runtime snapshot

    Returns True if bootstrap succeeded and snapshot was persisted.
    Returns False if bootstrap failed (exception logged).
    """
    try:
        import src.bootstrap.wiring.settings as settings_module
        from src.bootstrap.container.container import BootstrapContainer

        log.info("Refreshing runtime snapshot via official bootstrap...")

        # settings module itself acts as the config object (module-level variables)
        container = BootstrapContainer(settings_module)
        container.create()

        # Verify snapshot was actually persisted
        if _snapshot_exists_and_fresh():
            log.info("Runtime snapshot refreshed successfully.")
            return True
        else:
            log.error("Bootstrap completed but snapshot still missing or stale.")
            return False

    except Exception as exc:
        log.error("Bootstrap refresh failed: %s", exc)
        return False


def run_validation(refresh_snapshot: bool = True) -> int:
    """Run architecture validation with auto-refresh of stale snapshots.

    Flow:
    1. Check if snapshot exists and is fresh
    2. If missing or stale, attempt refresh via official bootstrap
    3. If refresh fails, exit with explicit error
    4. Run the architecture checker

    Returns 0 when no violations found, 1 otherwise.
    """
    # Step 1: Detect missing/stale snapshot
    if _snapshot_exists_and_fresh():
        log.info("Using existing fresh runtime snapshot.")
    else:
        log.info("Runtime snapshot missing or stale.")
        if not refresh_snapshot:
            log.error(
                "FATAL: Snapshot refresh is disabled (--no-refresh). "
                "Run validate-migration without --no-refresh after dependencies are ready."
            )
            return 1
        if not _refresh_snapshot_via_official_bootstrap():
            log.error("FATAL: Could not regenerate runtime snapshot. Fix bootstrap issues and re-run.")
            return 1

    # Step 4: Run the architecture checker
    from aioa.architecture.checker import run_architecture_checks

    violations = run_architecture_checks()

    if violations:
        print("Architecture violations found:")
        for violation in violations:
            print(f"  {violation}")
        return 1

    print("No architecture violations found.")
    return 0


def main() -> int:
    return run_validation(refresh_snapshot=True)


if __name__ == "__main__":
    raise SystemExit(main())
