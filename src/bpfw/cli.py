"""Terminal commands for Blueprint Framework."""

import argparse
from collections import Counter
import json
from pathlib import Path

from bpfw.shared.text import normalize_text_command


MVP_COMMANDS = (
    "init",
    "inspector",
    "editor",
    "planner",
    "verify",
    "run",
    "watch",
    "lock",
    "unlock",
    "status",
)

EXTENDED_COMMANDS = MVP_COMMANDS + ("intent", "history", "why", "trace", "batch", "normalize", "compact", "version", "authority", "migrate")


MAIN_HELP_TEXT = """Blueprint Framework

Usage:
  bpfw <command> [options]

Commands:
  init        Create or update .bpfw/blueprint.yaml from the current project.
  inspector   Review code blocks and assign purpose, domain, lifecycle, and metadata.
  editor      Edit existing blueprint authority entries.
  planner     Plan authority entries before code exists.
  verify      Check blueprint.yaml against the real code.
  run         Run a command only after bpfw verify passes.
  watch       Watch project changes and print drift feedback.
  lock        Lock protected authority files.
  unlock      Unlock protected authority files.
  status      Show project authority, drift, intent, logic, and evidence status.
  intent      Manage explicit intent-continuity decisions.
  history     Query the append-only Intent & Change Ledger.
  why         Explain why the current intent/history changed.
  trace       Map PATH:LINE to Blueprint ownership and history.
  batch       Plan/apply deterministic Blueprint changes in bulk.
  normalize   Normalize safe derivable Blueprint metadata.
  compact     Replace repeated artifact metadata with reusable profiles.
  authority   Inspect/diagnose/backup active SQLite authority.
  migrate     Preview and activate opt-in YAML to SQLite migration.
  version     Print the installed BPFW version.

Global options:
  -h, --help              Show this help message.
  --project-root PATH     Run BPFW from a specific project root.
  --json                  Print machine-readable output when supported.

Inspector:
  bpfw inspector          Open compact view.
  bpfw inspector -a       Open full view with all panels.
  bpfw inspector --all    Open full view with all panels.

Examples:
  bpfw init
  bpfw inspector
  bpfw inspector --all
  bpfw verify
  bpfw verify undeclared
  bpfw verify --all
  bpfw verify --deep
  bpfw intent accept --reason "approved requirement change"
  bpfw history perception_lab
  bpfw history search Rosetta
  bpfw why perception_lab
  bpfw trace internal/perception/lab.go:117
  bpfw batch audit --json
  bpfw batch generate-uids
  bpfw normalize
  bpfw compact --min-occurrences 3
  bpfw run -- python app.py
  bpfw watch
  bpfw status

Verify filters:
  bpfw verify [all|undeclared|missing|duplicate|clone|wrapper|effect|outcome|secret|invalid]
  bpfw verify --all
  bpfw verify --max N
"""


class BpfwArgumentParser(argparse.ArgumentParser):
    """Show BPFW help messages in the terminal."""

    def format_help(self) -> str:
        """Show the full BPFW help screen."""

        return f"{MAIN_HELP_TEXT}\n"

    def format_usage(self) -> str:
        """Show the short command format when input is wrong."""

        return "Usage:\n  bpfw <command> [options]\n"



def build_parser() -> argparse.ArgumentParser:
    """Build the command reader for BPFW terminal commands."""

    parser = BpfwArgumentParser(prog="bpfw")
    parser.add_argument("command", choices=EXTENDED_COMMANDS)
    parser.add_argument("subcommand", nargs="?")
    parser.add_argument("--project-root", default=".", metavar="PATH")
    parser.add_argument("--accept-scan", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--force-new", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument(
        "--allow-unprotected",
        action="store_true",
        help="Allow init to complete without OS authority protection.",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--once", action="store_true", dest="watch_once", help=argparse.SUPPRESS)
    parser.add_argument("--debounce-ms", type=int, default=800, dest="watch_debounce_ms", help=argparse.SUPPRESS)
    parser.add_argument("-a", "--all", action="store_true", dest="inspector_all", help=argparse.SUPPRESS)
    parser.add_argument("--max", type=int, default=8, dest="verify_max_items", help=argparse.SUPPRESS)
    parser.add_argument("--deep", action="store_true", dest="verify_deep", help="Run dynamic evidence through the managed PipeCraft runtime.")
    parser.add_argument("--reason", default=None, help="Reason for an explicit intent change acceptance.")
    return parser



def _run_command_after_verify(project_root: Path, command: list[str]) -> int:
    """Run a child command through the lazy runner import path."""

    from bpfw.runner import run_command_after_verify as real_run_command_after_verify

    return real_run_command_after_verify(project_root=project_root, command=command)


run_command_after_verify = _run_command_after_verify


def resolve_cli_command(command: str, subcommand: str | None) -> str:
    """Choose the engine command for the words typed by the user."""

    normalized_command = normalize_text_command(command)
    normalized_subcommand = normalize_text_command(subcommand) if subcommand is not None else None

    if normalized_command == "lock":
        if normalized_subcommand is not None:
            raise ValueError("lock does not accept subcommands")
        return "lock"
    if normalized_command == "unlock":
        if normalized_subcommand is not None and normalized_subcommand != "blueprint":
            raise ValueError("unlock only supports blueprint resource in MVP. Usage: bpfw unlock [blueprint]")
        return "unlock"
    if normalized_command == "inspector":
        if normalized_subcommand is not None:
            raise ValueError("inspector does not accept subcommands")
        return "inspector"
    if normalized_command == "editor":
        if normalized_subcommand is not None:
            raise ValueError("editor does not accept subcommands")
        return "editor"
    if normalized_command == "planner":
        if normalized_subcommand is not None:
            raise ValueError("planner does not accept subcommands")
        return "planner"
    if normalized_command == "init":
        if normalized_subcommand is not None:
            raise ValueError("init does not accept subcommands")
        return "init"
    if normalized_command == "verify":
        from bpfw.reports.verify_report import VERIFY_FINDING_FILTERS

        if normalized_subcommand is not None and normalized_subcommand not in VERIFY_FINDING_FILTERS:
            valid_filters = ", ".join(sorted(VERIFY_FINDING_FILTERS))
            raise ValueError(
                f"unknown verify filter: {normalized_subcommand}. "
                f"Supported filters: {valid_filters}"
            )
        return "verify"
    if normalized_command == "run":
        return "run"
    if normalized_command == "watch":
        if normalized_subcommand is not None:
            raise ValueError("watch does not accept subcommands")
        return "watch"
    if normalized_command == "status":
        if normalized_subcommand is not None:
            raise ValueError("status does not accept subcommands")
        return "status"
    if normalized_command == "intent":
        if normalized_subcommand != "accept":
            raise ValueError("intent requires subcommand 'accept'. Usage: bpfw intent accept --reason <reason>")
        return "intent"
    if normalized_command in {"history", "why", "trace"}:
        return normalized_command
    if normalized_command in {"migrate", "authority"}:
        return normalized_command
    if normalized_command == "batch":
        valid = {"audit", "discover-artifacts", "generate-uids", "set", "default", "remove", "rename-field", "replace-value", "move-path", "apply", "import", "export"}
        if normalized_subcommand not in valid:
            raise ValueError("batch requires one of: " + ", ".join(sorted(valid)))
        return "batch"
    if normalized_command in {"normalize", "compact"}:
        return normalized_command
    if normalized_command == "version":
        if normalized_subcommand is not None:
            raise ValueError("version does not accept subcommands")
        return "version"
    raise ValueError(f"Unknown command: {normalized_command}")


def _format_protected_resources(result: "ProtectionResult") -> str:
    """Show protected resources in terminal output."""

    lines = []
    for resource in result.protected_resources:
        lines.append(f"  {resource.path}")
    for resource in result.skipped_resources:
        lines.append(f"  {resource.path} (skipped: missing)")
    return "\n".join(lines)



def _build_payload(result) -> dict:  # noqa: ANN001
    """Convert an engine result to data that can be printed as JSON."""

    severity_rank = {"ok": 0, "info": 1, "warning": 2, "block": 3, "critical": 4}
    serialized_steps = [
        {
            "status": str(step.status).lower(),
            "message": step.message,
            "source": step.source,
            "details": step.details,
            "affected_resources": step.affected_resources,
            "suggested_actions": step.suggested_actions,
        }
        for step in result.steps
    ]
    if serialized_steps:
        primary_step = max(serialized_steps, key=lambda step: severity_rank.get(step["status"], 0))
        primary_message = primary_step["message"]
    else:
        primary_step = None
        primary_message = ""

    return {
        "command_name": result.command_name,
        "status": str(result.status).lower(),
        "message": primary_message,
        "primary_step": primary_step,
        "steps": serialized_steps,
    }



def _print_human(payload: dict) -> None:
    """Print readable command output."""

    # verify: print OK on success, error message otherwise
    if payload["command_name"] == "verify":
        if payload.get("status") in {"ok", "info", "warning"}:
            print("OK")
            return
        if payload.get("message"):
            print(payload["message"])
            return
        print(payload.get("status", "").upper())
        return

    # init: print message directly
    if payload["command_name"] == "init":
        if payload["message"]:
            print(payload["message"])
        return

    if payload["command_name"] == "status":
        details = payload.get("primary_step", {}).get("details", {})
        print("BPFW STATUS")
        print(f"  lock: {details.get('lock', 'unknown')}")
        print(f"  blueprint: {details.get('blueprint_state', 'unknown')}")
        print(f"  drift: {details.get('drift_state', 'unknown')}")
        print(f"  status: {details.get('status_state', 'unknown')}")
        return

    if payload["command_name"] in {"inspector", "editor", "planner"} and not payload["message"]:
        return

    # lock, unlock, inspector, editor, planner: print message directly
    if payload["message"]:
        print(payload["message"])
        return

    print(payload.get("status", "").upper())


def _run_drift_manager_preflight(project_root: Path, command_name: str) -> int:
    """Print a non-blocking drift preflight summary for interactive commands."""

    from bpfw.integrations.diff.review import DiffReviewService

    snapshot = DiffReviewService(project_root=project_root).load()
    if not snapshot.items:
        return 0

    kind_counts = Counter(item.kind.value for item in snapshot.items)
    top_kinds = ", ".join(
        f"{kind}={count}"
        for kind, count in kind_counts.most_common(3)
    )

    print(f"Drift detected before '{command_name}': continuing with warning.")
    print(f"Drift preflight: total={len(snapshot.items)} top={top_kinds}")
    print("Use 'bpfw status' to inspect drift summary before resolving items in editor/inspector.")
    return 0


def _print_status_drift_preview(project_root: Path, show_all: bool) -> None:
    """Print drift findings preview for status without blocking execution."""

    from bpfw.integrations.diff.review import DiffReviewService

    snapshot = DiffReviewService(project_root=project_root).load()
    if not snapshot.items:
        print("Drift preview: no drift items found.")
        return

    print(f"Drift preview: {len(snapshot.items)} item(s) detected.")
    max_items = len(snapshot.items) if show_all else 8
    for item in snapshot.items[:max_items]:
        print(f"  - [{item.kind.value}] {item.reason}")
    remaining = len(snapshot.items) - max_items
    if remaining > 0:
        print(f"  - ... {remaining} more drift item(s)")


def _print_status_drift_preview_from_report(report, show_all: bool) -> None:  # noqa: ANN001
    """Print a status drift preview from an already built verify report."""

    drift_findings = [
        finding
        for finding in report.findings
        if finding.code in {"UNDECLARED_CODE", "MISSING_DECLARED_CODE"}
    ]
    if not drift_findings:
        print("Drift preview: no drift items found.")
        return

    print(f"Drift preview: {len(drift_findings)} item(s) detected.")
    max_items = len(drift_findings) if show_all else 8
    for finding in drift_findings[:max_items]:
        print(f"  - [{finding.code}] {finding.message}")
    remaining = len(drift_findings) - max_items
    if remaining > 0:
        print(f"  - ... {remaining} more drift item(s)")


def _synchronize_authority_layout_for_status(project_root: Path) -> None:
    """Synchronize authority shards mechanically before rendering status."""

    from bpfw.core.authority import AuthorityRepository
    from bpfw.core.catalog.access_control import (
        authorize_blueprint_writes_for_tool,
        authorize_temporary_blueprint_unlock_for_tool,
    )
    from bpfw.core.errors import BlueprintLockedError

    from bpfw.core.authority.sqlite.migration import active_backend
    if active_backend(project_root) == "sqlite":
        return  # Relational authority has no physical shard layout to synchronize.
    try:
        repository = AuthorityRepository(project_root=project_root)
        document = repository.load()
    except FileNotFoundError:
        return
    except Exception as error:
        print(f"Shard sync skipped: could not load authority ({error}).")
        return

    try:
        with authorize_blueprint_writes_for_tool("status"):
            with authorize_temporary_blueprint_unlock_for_tool("status"):
                save_result = repository.save(document)
    except BlueprintLockedError as error:
        print(f"Shard sync skipped: {error}")
        return
    except Exception as error:
        print(f"Shard sync skipped: {error}")
        return

    if not save_result.created_shards and not save_result.removed_shards:
        print("Shard sync: no layout changes.")
        return

    print(
        "Shard sync:"
        f" created={len(save_result.created_shards)}"
        f" removed={len(save_result.removed_shards)}"
    )


def main() -> int:
    """Run the BPFW terminal command."""

    parser = build_parser()
    parsed_arguments, remaining_arguments = parser.parse_known_args()

    try:
        normalized_command = resolve_cli_command(
            command=parsed_arguments.command,
            subcommand=(None if parsed_arguments.command == "editor" else parsed_arguments.subcommand),
        )
    except ValueError as error:
        parser.error(str(error))

    # For extension commands, use the original token order: parse_known_args()
    # can consume a flag's value as the optional positional subcommand.
    import sys
    extension_tokens = list(sys.argv[2:])
    clean_tokens: list[str] = []
    omit_next = False
    for token in extension_tokens:
        if omit_next:
            omit_next = False
            continue
        if token == "--project-root":
            omit_next = True
            continue
        if token.startswith("--project-root=") or token == "--json":
            continue
        clean_tokens.append(token)

    if normalized_command in {"migrate", "authority"} or (
        normalized_command == "batch" and clean_tokens and clean_tokens[0] in {"import", "export"}
    ):
        from bpfw.core.authority.sqlite.commands import run_sqlite_cli
        try:
            return run_sqlite_cli(normalized_command, None,
                                  clean_tokens, Path(parsed_arguments.project_root).resolve(),
                                  parsed_arguments.as_json)
        except (ValueError, OSError, RuntimeError) as error:
            print(f"Authority error: {error}")
            return 1

    from bpfw.core.authority.sqlite.migration import active_backend
    try:
        sqlite_active = active_backend(Path(parsed_arguments.project_root).resolve()) == "sqlite"
    except RuntimeError as error:
        print(f"Authority error: {error}")
        return 1
    if normalized_command == "editor" and not sqlite_active:
        message = ("Editor requires SQLite authority; first run "
                   "bpfw migrate --to sqlite --plan and then --apply. "
                   "YAML is an import format, not a parallel Editor backend.")
        if parsed_arguments.as_json:
            import json
            print(json.dumps({"error":message,"required_backend":"sqlite"}))
        else:
            print(message)
        return 2
    if sqlite_active:
        if normalized_command == "editor":
            from bpfw.core.authority.sqlite.commands import run_sqlite_cli
            try:
                return run_sqlite_cli("editor", None, clean_tokens,
                                      Path(parsed_arguments.project_root).resolve(), parsed_arguments.as_json)
            except (ValueError, OSError, RuntimeError) as error:
                print(f"Editor error: {error}")
                return 1
        if normalized_command in {"lock", "unlock"}:
            from bpfw.core.authority.sqlite.commands import run_sqlite_cli
            try:
                return run_sqlite_cli(normalized_command, None, clean_tokens,
                                      Path(parsed_arguments.project_root).resolve(), parsed_arguments.as_json)
            except (ValueError, OSError, RuntimeError) as error:
                print(f"Authority protection error: {error}")
                return 1
        if normalized_command == "init":
            print("Cannot reinitialize a migrated SQLite project; use bpfw migrate on a legacy project.")
            return 2

    if normalized_command == "version":
        from importlib.metadata import PackageNotFoundError, version

        try:
            installed = version("blueprint-framework")
        except PackageNotFoundError:
            installed = "development"
        print(f"bpfw {installed}")
        return 0

    # init is handled directly by the catalog writer
    if normalized_command == "init":
        from bpfw.core.catalog.writer import run_init
        from bpfw.core.protection.runtime_lease import runtime_blueprint_write_lease

        project_root = Path(parsed_arguments.project_root).resolve()
        try:
            with runtime_blueprint_write_lease(project_root=project_root, tool_name="init"):
                _success, message, exit_code = run_init(
                    project_root=project_root,
                    allow_unprotected=parsed_arguments.allow_unprotected,
                )
        except Exception as error:
            print(f"Init error: {error}")
            return 1
        print(message)
        return exit_code

    # verify is handled directly by the catalog verify pipeline
    if normalized_command == "verify":
        from bpfw.core.catalog.verification_cache import _load_fast_cached_verification_report
        from bpfw.reports.verify_report import VERIFY_FINDING_FILTERS, render_verify_report

        project_root = Path(parsed_arguments.project_root).resolve()
        selected_filter = normalize_text_command(parsed_arguments.subcommand) if parsed_arguments.subcommand else None
        selected_codes = None if selected_filter in {None, "all"} else sorted(VERIFY_FINDING_FILTERS[selected_filter])
        max_items = 0 if parsed_arguments.inspector_all else parsed_arguments.verify_max_items
        cached_result = _load_fast_cached_verification_report(project_root=project_root)
        if cached_result is None:
            from bpfw.core.catalog.verify import run_verify

            report, exit_code = run_verify(project_root=project_root, deep=parsed_arguments.verify_deep, capture_history=False)
        else:
            report, exit_code = cached_result
        output = render_verify_report(
            report,
            finding_codes=selected_codes,
            max_items_per_group=max_items,
        )
        print(output)
        try:
            from bpfw.core.catalog.loader import BlueprintLoader
            from bpfw.core.history.ledger import capture_artifact_state
            current_load = BlueprintLoader(project_root=project_root).load()
            if isinstance(current_load.data, dict) and current_load.state not in {"missing", "invalid"}:
                capture_artifact_state(project_root, current_load.data, trigger="bpfw verify")
        except Exception:
            pass
        return exit_code

    # Intent continuity changes are explicit authority decisions.
    if normalized_command == "intent":
        from bpfw.core.catalog.loader import BlueprintLoader
        from bpfw.core.intent import IntentContinuityManager

        project_root = Path(parsed_arguments.project_root).resolve()
        reason = (parsed_arguments.reason or "").strip()
        if not reason:
            print("Intent acceptance requires --reason <reason>.")
            return 1
        load_result = BlueprintLoader(project_root=project_root).load()
        if load_result.domain_document is None or (load_result.domain_document.version or 1) < 2:
            print("Intent continuity requires a Blueprint v2 authority document.")
            return 1
        entry = IntentContinuityManager(project_root).accept(load_result.domain_document, reason=reason)
        print("Intent change accepted.\n")
        print(f"Previous: {entry.get('previous_fingerprint') or '-'}")
        print(f"Current:  {entry.get('new_fingerprint')}")
        print(f"Reason:   {entry.get('reason')}")
        return 0

    # Semantic history queries are served from the append-only ledger/index.
    if normalized_command in {"history", "why", "trace"}:
        from bpfw.core.history.commands import render_events, render_trace, trace_location
        from bpfw.core.history.ledger import HistoryLedger
        project_root = Path(parsed_arguments.project_root).resolve()
        target = parsed_arguments.subcommand
        if normalized_command == "history" and target == "compact":
            import json
            from bpfw.core.history.compaction import apply_history_compaction, plan_history_compaction
            result = {"plan": plan_history_compaction(project_root), "applied": False}
            if "--apply" in remaining_arguments or "--apply" in sys.argv[2:]:
                result.update(apply_history_compaction(project_root))
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        history_search = False
        if normalized_command == "history" and target == "search":
            target = " ".join(remaining_arguments).strip() or None
            remaining_arguments = []
            history_search = True
        elif remaining_arguments:
            target = " ".join([part for part in ([target] if target else []) + remaining_arguments]).strip() or None
            remaining_arguments = []
        ledger = HistoryLedger(project_root)
        if normalized_command == "history":
            events = ledger.search(target, limit=100) if history_search and target else ledger.query(target, limit=100)
            if parsed_arguments.as_json:
                print(json.dumps(events, indent=2, ensure_ascii=False))
            else:
                print(render_events(events))
            return 0
        if not target:
            print(f"{normalized_command} requires a target.")
            return 1
        if normalized_command == "why":
            events = ledger.why(target)
            if parsed_arguments.as_json:
                print(json.dumps(events, indent=2, ensure_ascii=False))
            else:
                print(render_events(events, title=f"WHY — {target}"))
            return 0 if events else 1
        traced = trace_location(project_root, target)
        if parsed_arguments.as_json:
            print(json.dumps(traced, indent=2, ensure_ascii=False))
        else:
            print(render_trace(traced))
        return 0 if not traced.get("error") else 1

    # Deterministic Blueprint Automation keeps repetitive edits out of the LLM.
    if normalized_command in {"batch", "normalize", "compact"}:
        from bpfw.core.automation.commands import run_automation_cli
        import sys
        raw_tokens = list(sys.argv[2:])
        cleaned: list[str] = []
        skip = False
        for index, token in enumerate(raw_tokens):
            if skip:
                skip = False
                continue
            if token == "--project-root":
                skip = True
                continue
            if token.startswith("--project-root=") or token == "--json":
                continue
            cleaned.append(token)
        automation_subcommand = None
        if normalized_command == "batch" and cleaned:
            automation_subcommand = cleaned.pop(0)
        return run_automation_cli(
            normalized_command, automation_subcommand, cleaned,
            Path(parsed_arguments.project_root).resolve(), parsed_arguments.as_json,
        )

    # run is handled directly by verification gate plus subprocess execution
    if normalized_command == "run":
        project_root = Path(parsed_arguments.project_root).resolve()
        command: list[str] = []
        if parsed_arguments.subcommand is not None:
            command.append(parsed_arguments.subcommand)
        command.extend(remaining_arguments)
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            print("Missing command.\n")
            print("Usage:")
            print("  bpfw run -- <command>")
            return 1
        return run_command_after_verify(project_root=project_root, command=command)

    if remaining_arguments:
        parser.error(f"unrecognized arguments: {' '.join(remaining_arguments)}")

    # watch is handled directly by the lightweight watch service
    if normalized_command == "watch":
        from bpfw.watch import WatchDependencyError, run_watch

        project_root = Path(parsed_arguments.project_root).resolve()
        try:
            return run_watch(
                project_root=project_root,
                debounce_ms=parsed_arguments.watch_debounce_ms,
                once=parsed_arguments.watch_once,
            )
        except WatchDependencyError as error:
            print(str(error))
            return 1

    # status is handled directly by a single-pass status report pipeline
    if normalized_command == "status":
        from bpfw.core.catalog.verification_cache import _load_fast_cached_verification_snapshot
        from bpfw.core.protection.authority import get_authority_protection_status
        from bpfw.reports.status_report import render_status_report, run_status

        project_root = Path(parsed_arguments.project_root).resolve()
        cached_snapshot = _load_fast_cached_verification_snapshot(project_root=project_root)
        if cached_snapshot is not None:
            report, exit_code, status_context = cached_snapshot
            _print_status_drift_preview_from_report(
                report=report,
                show_all=parsed_arguments.inspector_all,
            )
            lock_state = get_authority_protection_status(project_root=project_root).status
            output = render_status_report(
                report=report,
                blueprint_path=str(status_context.get("blueprint_path", ".bpfw/blueprint.yaml")),
                lock_state=lock_state,
                lifecycle_counts=status_context.get("lifecycle_counts", {}),
                authority_config=status_context.get("authority_config", {}),
                included_shards_count=status_context.get("included_shards_count", 0),
            )
            print(output)
            return exit_code

        from bpfw.core.catalog.loader import BlueprintLoader
        from bpfw.core.catalog.verify import run_verify

        load_result = BlueprintLoader(project_root=project_root).load()
        report, _verify_exit_code = run_verify(
            project_root=project_root,
            precomputed_load_result=load_result,
        )
        _print_status_drift_preview_from_report(
            report=report,
            show_all=parsed_arguments.inspector_all,
        )
        output, exit_code = run_status(
            project_root=project_root,
            precomputed_load_result=load_result,
            precomputed_verify_report=report,
        )
        print(output)
        if load_result.domain_document is not None and (load_result.domain_document.version or 1) >= 2:
            from bpfw.reports.system_status import render_system_status
            print("\n" + render_system_status(report))
        return exit_code

    # lock is handled directly by the protection authority
    if normalized_command == "lock":
        from bpfw.core.catalog.paths import CANONICAL_BLUEPRINT_FILE
        from bpfw.core.protection.authority import MISSING_BLUEPRINT_STATUS, lock_authority

        project_root = Path(parsed_arguments.project_root).resolve()
        lock_result = lock_authority(project_root=project_root)
        if lock_result.status == MISSING_BLUEPRINT_STATUS:
            print(
                "BPFW blueprint does not exist:\n"
                f"  {CANONICAL_BLUEPRINT_FILE}\n\n"
                "Run bpfw init first."
            )
            return 1
        if lock_result.status == "unsupported":
            print(
                "BPFW could not lock authority resources.\n\n"
                "Protected:\n"
                f"{_format_protected_resources(result=lock_result)}\n\n"
                "Status:\n"
                "  UNSUPPORTED\n\n"
                "Try running from a terminal where file permissions can be changed."
            )
            return 1
        if lock_result.status == "degraded":
            print(
                "Blueprint partially locked.\n\n"
                "Protected:\n"
                f"{_format_protected_resources(result=lock_result)}\n\n"
                "Status:\n"
                "  DEGRADED\n\n"
                "Reason:\n"
                "  Strong OS protection is unavailable, but read-only protection was applied."
            )
            return 0
        if lock_result.status != "locked":
            print(
                "BPFW authority protection is incomplete.\n\n"
                "Protected:\n"
                f"{_format_protected_resources(result=lock_result)}\n\n"
                "Status:\n"
                f"  {lock_result.status.upper()}"
            )
            return 1
        print(
            "Blueprint locked.\n\n"
            "Protected:\n"
            f"{_format_protected_resources(result=lock_result)}\n\n"
            "Status:\n"
            "  LOCKED"
        )
        return 0

    # unlock is handled directly by the protection authority
    if normalized_command == "unlock":
        from bpfw.core.catalog.paths import CANONICAL_BLUEPRINT_FILE
        from bpfw.core.protection.autolock import _start_autolock_after_unlock
        from bpfw.core.protection.authority import (
            MISSING_BLUEPRINT_STATUS,
            get_authority_protection_status,
            unlock_authority,
        )
        from bpfw.core.protection.os_lock import verify_unlock_permission

        project_root = Path(parsed_arguments.project_root).resolve()
        current_lock_state = get_authority_protection_status(project_root=project_root).status
        if current_lock_state == MISSING_BLUEPRINT_STATUS:
            print(
                "BPFW blueprint does not exist:\n"
                f"  {CANONICAL_BLUEPRINT_FILE}\n\n"
                "Run bpfw init first."
            )
            return 1
        if not verify_unlock_permission():
            print(
                "Authentication failed.\n\n"
                "Cannot unlock authority files without proper authentication."
            )
            return 1
        unlock_result = unlock_authority(project_root=project_root)
        if unlock_result.status == "unsupported":
            print(
                "BPFW could not unlock authority resources.\n\n"
                "Protected:\n"
                f"{_format_protected_resources(result=unlock_result)}\n\n"
                "Status:\n"
                "  UNSUPPORTED\n\n"
                "Try running from a terminal where file permissions can be changed."
            )
            return 1
        autolock_started = False
        if unlock_result.status == "unlocked":
            autolock_started = _start_autolock_after_unlock(project_root=project_root)

        autolock_lines = (
            "Auto-lock:\n"
            "  scheduled after 30 seconds of authority inactivity\n"
            "  blueprint or shard changes reset the countdown"
            if autolock_started
            else "Auto-lock:\n  not scheduled"
        )
        print(
            "Blueprint unlocked.\n\n"
            "Protected:\n"
            f"{_format_protected_resources(result=unlock_result)}\n\n"
            "Status:\n"
            f"  {unlock_result.status.upper()}\n\n"
            f"{autolock_lines}\n\n"
            "Reminder:\n"
            "  Run bpfw verify before locking again."
        )
        return 0

    from bpfw.core.engine import BlueprintEngine, build_command

    engine = BlueprintEngine()
    command_arguments: dict[str, str] = {}

    if normalized_command == "inspector" and parsed_arguments.inspector_all:
        command_arguments["view"] = "all"

    result = engine.run(
        build_command(
            command_name=normalized_command,
            project_root=Path(parsed_arguments.project_root).resolve(),
            arguments=command_arguments,
        )
    )
    payload = _build_payload(result)

    if parsed_arguments.as_json:
        print(json.dumps(payload, indent=2))
    else:
        _print_human(payload)

    return 0 if result.status in {"OK", "INFO", "WARNING"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
