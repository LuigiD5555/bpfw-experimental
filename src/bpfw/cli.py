"""Unified CLI for BPFW architecture and catalog authority commands."""

import argparse
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BPFW unified CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("check-architecture")
    validate_parser = subparsers.add_parser("validate-migration")
    validate_parser.add_argument(
        "--no-refresh",
        action="store_true",
        help="Do not refresh runtime snapshot via bootstrap.",
    )
    subparsers.add_parser("lock")
    subparsers.add_parser("unlock")
    subparsers.add_parser("status")
    subparsers.add_parser("run-guard")
    subparsers.add_parser("check-implementation-existence")
    subparsers.add_parser("check-entrypoint-implementation")
    subparsers.add_parser("check-executables")
    subparsers.add_parser("preflight")
    idle_parser = subparsers.add_parser("idle-autolock")
    idle_parser.add_argument("--idle-seconds", type=int, default=30)

    arguments = parser.parse_args(argv)
    if arguments.command == "check-architecture":
        from bpfw.architecture.checker import main as check_architecture_main
        return check_architecture_main()
    if arguments.command == "validate-migration":
        from bpfw.architecture.validate_migration import run_validation as validate_migration_run
        return validate_migration_run(refresh_snapshot=not arguments.no_refresh)
    if arguments.command == "lock":
        from bpfw.catalog.authority import lock_catalog_command
        return lock_catalog_command()
    if arguments.command == "unlock":
        from bpfw.catalog.authority import unlock_catalog_command
        return unlock_catalog_command(require_sudo=True)
    if arguments.command == "status":
        from bpfw.catalog.status import status_catalog_command
        return status_catalog_command()
    if arguments.command == "run-guard":
        from bpfw.catalog.authority import run_guard
        return run_guard()
    if arguments.command == "idle-autolock":
        from bpfw.catalog.authority import run_idle_autolock
        return run_idle_autolock(arguments.idle_seconds)
    if arguments.command == "check-implementation-existence":
        from bpfw.architecture.catalog_validation import check_implementation_existence_main
        return check_implementation_existence_main()
    if arguments.command == "check-entrypoint-implementation":
        from bpfw.architecture.catalog_validation import check_entrypoint_implementation_main
        return check_entrypoint_implementation_main()
    if arguments.command == "check-executables":
        from bpfw.execution.executable_catalog import check_executables_main
        return check_executables_main()
    if arguments.command == "preflight":
        from bpfw.execution.executable_catalog import check_executables_main
        from bpfw.architecture.validate_migration import run_validation as validate_migration_run
        executable_check_exit_code = check_executables_main()
        if executable_check_exit_code != 0:
            return executable_check_exit_code
        return validate_migration_run(refresh_snapshot=False)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
