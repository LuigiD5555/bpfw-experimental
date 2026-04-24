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
import os
import importlib
import sys

from bpfw.catalog.access_control import (
    CatalogLockedError,
    CatalogStateCheckError,
    ExternalCatalogWriteBlockedError,
    assert_catalog_write_scope,
    assert_catalog_writable,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)


def _snapshot_exists_and_fresh() -> bool:
    """Check if a valid runtime snapshot exists.

    Returns True only if the snapshot file exists and its catalog_hash
    matches the current catalog state.
    """
    from bpfw.catalog.runtime_snapshot import load_persisted_runtime_snapshot
    return load_persisted_runtime_snapshot() is not None


def _get_bootstrap_adapter_reference() -> str:
    """Return dotted path to the project bootstrap adapter callable.

    The adapter must be a callable with no arguments returning bool:
    - True: snapshot refresh succeeded
    - False: snapshot refresh failed
    """
    return os.environ.get(
        "BPFW_BOOTSTRAP_ADAPTER",
        "src.bootstrap.wiring.bpfw_adapter.refresh_runtime_snapshot",
    ).strip()


def _refresh_snapshot_via_project_adapter() -> bool:
    """Execute project-provided bootstrap adapter to regenerate runtime snapshot.

    BPFW does not import project bootstrap modules directly.
    Instead, the project exposes a small adapter callable and BPFW invokes it.

    Returns True if bootstrap succeeded and snapshot was persisted.
    Returns False if bootstrap failed (exception logged).
    """
    adapter_reference = _get_bootstrap_adapter_reference()
    if not adapter_reference:
        log.error("Bootstrap refresh failed: empty BPFW_BOOTSTRAP_ADAPTER.")
        return False

    module_path, separator, callable_name = adapter_reference.rpartition(".")
    if not separator or not module_path or not callable_name:
        log.error(
            "Bootstrap refresh failed: invalid adapter reference '%s'. "
            "Expected 'package.module.callable'.",
            adapter_reference,
        )
        return False

    try:
        adapter_module = importlib.import_module(module_path)
        adapter_callable = getattr(adapter_module, callable_name)
    except Exception as exc:
        log.error("Bootstrap refresh failed: cannot load adapter '%s': %s", adapter_reference, exc)
        return False

    if not callable(adapter_callable):
        log.error("Bootstrap refresh failed: adapter '%s' is not callable.", adapter_reference)
        return False

    try:
        log.info("Refreshing runtime snapshot via project bootstrap adapter...")
        refresh_result = bool(adapter_callable())
        if not refresh_result:
            log.error("Project bootstrap adapter returned failure.")
            return False
        # Verify snapshot was actually persisted
        if _snapshot_exists_and_fresh():
            log.info("Runtime snapshot refreshed successfully.")
            return True
        log.error("Project bootstrap completed but snapshot still missing or stale.")
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
            log.error("What to verify:")
            log.error("- The runtime dependencies required by the project bootstrap are reachable.")
            log.error("- BPFW_BOOTSTRAP_ADAPTER points to the correct refresh callable.")
            log.error("- The last runtime snapshot is not missing or stale because of recent catalog edits.")
            return 1
        try:
            assert_catalog_write_scope()
            assert_catalog_writable()
        except (CatalogLockedError, CatalogStateCheckError, ExternalCatalogWriteBlockedError) as exc:
            log.error("FATAL: %s", exc)
            return 1
        if not _refresh_snapshot_via_project_adapter():
            log.error("FATAL: Could not regenerate runtime snapshot. Fix bootstrap issues and re-run.")
            log.error("What to verify:")
            log.error("- BootstrapContainer.create() completes successfully with current dependencies.")
            log.error("- The bootstrap adapter persists a fresh runtime snapshot.")
            log.error("- The catalog, runtime contract, and wiring verifier all pass during bootstrap.")
            return 1

    # Step 4: Run the architecture checker
    from bpfw.architecture.checker import format_violations_report
    from bpfw.architecture.checker import run_architecture_checks

    violations = run_architecture_checks()

    if violations:
        print(format_violations_report(violations))
        return 1

    print("No architecture violations found.")
    return 0


def main() -> int:
    return run_validation(refresh_snapshot=True)


if __name__ == "__main__":
    raise SystemExit(main())
