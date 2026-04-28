"""Command line interface for Blueprint Framework."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from bpfw.core.engine import BlueprintEngine, build_command
from bpfw.enforcement.ci import ci_exit_code, render_ci_report


SUPPORTED_COMMANDS = (
    "init",
    "verify",
    "verify-integrity",
    "install-hooks",
    "manifest",
    "start",
    "approve",
    "approvals",
    "discover",
    "proposals",
    "show-proposal",
    "accept-proposal",
    "reject-proposal",
    "review",
    "apply",
    "reject",
    "status",
    "architecture",
    "composition",
    "runtime",
    "wiring",
    "access",
    "blueprint",
)



def build_parser() -> argparse.ArgumentParser:
    """Create CLI parser for base BPFW commands."""

    parser = argparse.ArgumentParser(prog="bpfw")
    parser.add_argument("command", choices=SUPPORTED_COMMANDS)
    parser.add_argument("subcommand", nargs="?")
    parser.add_argument("target", nargs="?")
    parser.add_argument("operand", nargs="?")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--scope", default="")
    parser.add_argument("--responsibility", default="")
    parser.add_argument("--as-new-responsibility", dest="as_new_responsibility", default="")
    parser.add_argument("--state", default="")
    parser.add_argument("--reject-action", default="")
    parser.add_argument("--accept-scan", action="store_true")
    parser.add_argument("--force-new", action="store_true")
    parser.add_argument("--ci", action="store_true", dest="ci_mode")
    parser.add_argument("--diagnostic", action="store_true")
    parser.add_argument("--operation", default="")
    parser.add_argument("--reason", default="")
    parser.add_argument("--duration-minutes", dest="duration_minutes", default="30")
    parser.add_argument("--request-id", dest="request_id", default="")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--layer", default="")
    return parser



def normalize_command(command: str, subcommand: str | None, target: str | None, operand: str | None) -> str:
    """Map CLI tokens into engine command names."""

    if command == "manifest":
        if subcommand != "write":
            raise ValueError("manifest command requires subcommand `write`")
        return "manifest_write"
    if command == "init":
        if subcommand is not None:
            raise ValueError("init command does not accept subcommands")
        return "init"
    if command == "start":
        if subcommand is None:
            raise ValueError("start command requires a change_id")
        return "start"
    if command == "approve":
        if subcommand is None:
            raise ValueError("approve command requires a request_id")
        return "approve"
    if command == "approvals":
        if subcommand is not None:
            raise ValueError("approvals command does not accept subcommands")
        return "approvals"
    if command == "verify-integrity":
        if subcommand is not None:
            raise ValueError("verify-integrity command does not accept subcommands")
        return "verify_integrity"
    if command == "install-hooks":
        if subcommand is not None:
            raise ValueError("install-hooks command does not accept subcommands")
        return "install_hooks"
    if command == "review":
        if subcommand is None:
            raise ValueError("review command requires a change_id")
        return "review"
    if command == "apply":
        if subcommand is None:
            raise ValueError("apply command requires a change_id")
        return "apply"
    if command == "reject":
        if subcommand is None:
            raise ValueError("reject command requires a change_id")
        return "reject"
    if command == "architecture":
        if subcommand != "check":
            raise ValueError("architecture command requires subcommand `check`")
        return "architecture_check"
    if command == "composition":
        if subcommand != "check":
            raise ValueError("composition command requires subcommand `check`")
        return "composition_check"
    if command == "runtime":
        if subcommand != "snapshot":
            raise ValueError("runtime command requires subcommand `snapshot`")
        return "runtime_snapshot"
    if command == "wiring":
        if subcommand != "check":
            raise ValueError("wiring command requires subcommand `check`")
        return "wiring_check"
    if command == "show-proposal":
        if subcommand is None:
            raise ValueError("show-proposal command requires a proposal_id")
        return "show_proposal"
    if command == "accept-proposal":
        if subcommand is None:
            raise ValueError("accept-proposal command requires a proposal_id")
        return "accept_proposal"
    if command == "reject-proposal":
        if subcommand is None:
            raise ValueError("reject-proposal command requires a proposal_id")
        return "reject_proposal"
    if command == "access":
        if subcommand not in {"request", "grant", "list"}:
            raise ValueError("access command requires subcommand `request`, `grant`, or `list`")
        if subcommand == "list" and target is not None:
            raise ValueError("access list does not accept target")
        if subcommand in {"request", "grant"} and target is None:
            raise ValueError(f"access {subcommand} requires target")
        return f"access_{subcommand}"
    if command == "blueprint":
        if subcommand == "add-file":
            if target is None or operand is None:
                raise ValueError("blueprint add-file requires <responsibility_id> and <path>")
            return "blueprint_add_file"
        if subcommand == "add-symbol":
            if target is None or operand is None:
                raise ValueError("blueprint add-symbol requires <responsibility_id> and <symbol>")
            return "blueprint_add_symbol"
        if subcommand == "create-responsibility":
            if target is None:
                raise ValueError("blueprint create-responsibility requires <responsibility_id>")
            return "blueprint_create_responsibility"
        raise ValueError("blueprint command requires subcommand `add-file`, `add-symbol`, or `create-responsibility`")

    if subcommand is not None:
        raise ValueError(f"Command `{command}` does not accept subcommands")
    return command



def _build_payload(result) -> dict:  # noqa: ANN001
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
    if payload["command_name"] == "access_request" and payload.get("status") == "ok":
        details = (payload.get("primary_step") or {}).get("details", {})
        print("Authority access request created.\n")
        print("Request ID:")
        print(details.get("request_id", ""))
        print("\nResource:")
        print(details.get("resource_path", ""))
        print("\nScope:")
        print(details.get("scope", ""))
        print("\nOperation:")
        print(details.get("operation", ""))
        print("\nThis does not unlock the full Blueprint.")
        print("It only requests permission for this operation.")
        return
    if payload["command_name"] == "access_grant" and payload.get("status") == "ok":
        details = (payload.get("primary_step") or {}).get("details", {})
        print("Authority access granted.\n")
        print("Grant ID:")
        print(details.get("grant_id", ""))
        print("\nResource:")
        print(details.get("resource_path", ""))
        print("\nScope:")
        print(details.get("scope", ""))
        print("\nAllowed operation:")
        print(details.get("operation", ""))
        print("\nExpires at:")
        print(details.get("expires_at", ""))
        return
    if payload["command_name"] == "access_list" and payload.get("status") == "ok":
        details = (payload.get("primary_step") or {}).get("details", {})
        print("Authority access list.\n")
        print("Pending requests:")
        print(details.get("pending_requests_human", "") or "(none)")
        print("\nActive grants:")
        print(details.get("active_grants_human", "") or "(none)")
        return
    if payload["command_name"] == "init":
        if payload["message"]:
            print(payload["message"])
        return
    primary_step = payload.get("primary_step") or {}
    details = primary_step.get("details", {})
    if details.get("error_code") == "RV012":
        affected_resource = ""
        affected_resources = primary_step.get("affected_resources", [])
        if affected_resources:
            affected_resource = Path(affected_resources[0]).name
        if not affected_resource:
            message = payload.get("message", "")
            marker = "authority resource:"
            if marker in message:
                affected_resource = message.split(marker, maxsplit=1)[1].split(".", maxsplit=1)[0].strip()
        print("BLOCK\n")
        print("Workspace attempted to modify authority resource:")
        print(affected_resource or "(unknown)")
        print("\nDirect authority edits are not allowed.\n")
        print("Do not retry this edit.\n")
        print("Allowed next action:")
        print("Create a proposal or use a scoped authority command.")
        return

    print(f"Command: {payload['command_name']}")
    print(f"Status: {payload['status'].upper()}")
    if payload["message"]:
        print(f"Message: {payload['message']}")

    primary_step = payload.get("primary_step")
    if primary_step is None:
        return

    details = primary_step.get("details", {})
    if "error_code" in details:
        print(f"Error Code: {details['error_code']}")
    if "blueprint_path" in details:
        print(f"Blueprint: {details['blueprint_path']}")
    if "responsibility_count" in details:
        print(f"Responsibilities: {details['responsibility_count']}")
    if "architecture_profile_id" in details and details["architecture_profile_id"]:
        print(f"Architecture Profile: {details['architecture_profile_id']}")
    if "runtime_snapshot_human" in details:
        print("Runtime Snapshot:")
        print(details["runtime_snapshot_human"])
    if "active_bindings_count" in details:
        print(f"Active Bindings: {details['active_bindings_count']}")
    if "warning_count" in details:
        print(f"Runtime Warnings: {details['warning_count']}")
    if "wiring_issue_count" in details:
        print(f"Wiring Issues: {details['wiring_issue_count']}")
    if "duplication_total_count" in details:
        print(f"Duplication Findings: {details['duplication_total_count']}")
    if "duplication_block_count" in details:
        print(f"Duplication Blocks: {details['duplication_block_count']}")
    if "duplication_warning_count" in details:
        print(f"Duplication Warnings: {details['duplication_warning_count']}")
    if "duplication_findings_human" in details:
        print("Duplication Summary:")
        print(details["duplication_findings_human"])
    if "blueprint_mode_enabled" in details:
        print(f"Blueprint Mode Enabled: {details['blueprint_mode_enabled']}")
    if "blueprint_mode_operation_count" in details:
        print(f"Blueprint Mode Operations: {details['blueprint_mode_operation_count']}")
    if "blueprint_mode_issue_count" in details:
        print(f"Blueprint Mode Issues: {details['blueprint_mode_issue_count']}")
    if "manifest_path" in details:
        print(f"Manifest: {details['manifest_path']}")
    if "integrity_checked_files" in details:
        print(f"Checked Files: {details['integrity_checked_files']}")
    if "manifest_updated_at" in details:
        print(f"Updated At: {details['manifest_updated_at']}")
    if "approval_id" in details:
        print(f"Approval ID: {details['approval_id']}")
    if "request_id" in details:
        print(f"Request ID: {details['request_id']}")
    if "approval_backend" in details:
        print(f"Approval Backend: {details['approval_backend']}")
    if "approval_approved_by" in details:
        print(f"Approved By: {details['approval_approved_by']}")
    if "approval_count" in details:
        print(f"Approvals: {details['approval_count']}")
    if "approval_issue_count" in details:
        print(f"Approval Issues: {details['approval_issue_count']}")
    if "workspace_path" in details:
        print(f"Workspace: {details['workspace_path']}")
    if "scope_resource_id" in details:
        print(f"Scope: {details['scope_resource_id']}")
    if "allowed_file_count" in details:
        print(f"Allowed Files: {details['allowed_file_count']}")
    if "change_id" in details:
        print(f"Change ID: {details['change_id']}")
    if "review_status" in details:
        print(f"Review: {details['review_status']}")
    if "changed_file_count" in details:
        print(f"Changed Files: {details['changed_file_count']}")
    if "applied_file_count" in details:
        print(f"Applied Files: {details['applied_file_count']}")
    if "transaction_path" in details:
        print(f"Transaction: {details['transaction_path']}")
    if "discover_proposal_count" in details:
        print(f"Created Proposals: {details['discover_proposal_count']}")
    if "discover_pending_count" in details:
        print(f"Pending Proposals: {details['discover_pending_count']}")
    if "proposal_id" in details:
        print(f"Proposal ID: {details['proposal_id']}")
    if "proposal_status" in details:
        print(f"Proposal Status: {details['proposal_status']}")
    if "proposal_risk" in details:
        print(f"Proposal Risk: {details['proposal_risk']}")
    if "proposals_human" in details:
        print("Proposals:")
        print(details["proposals_human"])
    if "proposal_human" in details:
        print("Proposal Detail:")
        print(details["proposal_human"])
    if "proposal_action" in details:
        print(f"Action: {details['proposal_action']}")
    if "moved_file_count" in details:
        print(f"Moved Files: {details['moved_file_count']}")
    if "installed_hook_path" in details:
        print(f"Installed Hook: {details['installed_hook_path']}")

    affected_resources = primary_step.get("affected_resources", [])
    if affected_resources:
        print(f"Affected File: {affected_resources[0]}")

    suggested_actions = primary_step.get("suggested_actions", [])
    if suggested_actions:
        print(f"Recommendation: {suggested_actions[0]}")



def main() -> int:
    """Entry point for executable scaffold commands."""

    parser = build_parser()
    parsed_arguments = parser.parse_args()

    try:
        normalized_command = normalize_command(
            command=parsed_arguments.command,
            subcommand=parsed_arguments.subcommand,
            target=parsed_arguments.target,
            operand=parsed_arguments.operand,
        )
    except ValueError as error:
        parser.error(str(error))

    engine = BlueprintEngine()
    command_arguments: dict[str, str] = {}
    if normalized_command == "approve" and parsed_arguments.subcommand is not None:
        command_arguments["request_id"] = parsed_arguments.subcommand
    if normalized_command in {"start", "review", "apply", "reject"} and parsed_arguments.subcommand is not None:
        command_arguments["change_id"] = parsed_arguments.subcommand
    if normalized_command in {"show_proposal", "accept_proposal", "reject_proposal"} and parsed_arguments.subcommand is not None:
        command_arguments["proposal_id"] = parsed_arguments.subcommand
    if normalized_command == "start" and parsed_arguments.scope:
        command_arguments["scope"] = parsed_arguments.scope
    if normalized_command == "accept_proposal":
        if parsed_arguments.responsibility:
            command_arguments["responsibility"] = parsed_arguments.responsibility
        if parsed_arguments.as_new_responsibility:
            command_arguments["as_new_responsibility"] = parsed_arguments.as_new_responsibility
        if parsed_arguments.state:
            command_arguments["state"] = parsed_arguments.state
    if normalized_command == "reject_proposal" and parsed_arguments.reject_action:
        command_arguments["reject_action"] = parsed_arguments.reject_action
    if normalized_command == "verify" and parsed_arguments.ci_mode:
        command_arguments["ci"] = "true"
    if normalized_command == "verify" and parsed_arguments.diagnostic:
        command_arguments["diagnostic"] = "true"
    if normalized_command == "access_request":
        command_arguments["resource_id"] = parsed_arguments.target
        command_arguments["operation"] = parsed_arguments.operation
        command_arguments["scope"] = parsed_arguments.scope
        command_arguments["reason"] = parsed_arguments.reason
    if normalized_command == "access_grant":
        command_arguments["request_id"] = parsed_arguments.target
        command_arguments["duration_minutes"] = parsed_arguments.duration_minutes
    if normalized_command == "blueprint_add_file":
        command_arguments["responsibility_id"] = parsed_arguments.target or ""
        command_arguments["file_path"] = parsed_arguments.operand or ""
    if normalized_command == "blueprint_add_symbol":
        command_arguments["responsibility_id"] = parsed_arguments.target or ""
        command_arguments["symbol_name"] = parsed_arguments.operand or ""
    if normalized_command == "blueprint_create_responsibility":
        command_arguments["responsibility_id"] = parsed_arguments.target or ""
        command_arguments["owner_layer"] = parsed_arguments.layer or ""
    if normalized_command == "init":
        if parsed_arguments.accept_scan:
            command_arguments["accept_scan"] = "true"
        if parsed_arguments.force_new:
            command_arguments["force_new"] = "true"
    result = engine.run(
        build_command(
            command_name=normalized_command,
            project_root=Path(parsed_arguments.project_root).resolve(),
            arguments=command_arguments,
        )
    )
    payload = _build_payload(result)
    if parsed_arguments.as_json:
        primary_step = payload.get("primary_step") or {}
        details = primary_step.get("details", {})
        runtime_snapshot_json = details.get("runtime_snapshot_json")
        if normalized_command == "runtime_snapshot" and isinstance(runtime_snapshot_json, str):
            print(runtime_snapshot_json)
        else:
            print(json.dumps(payload, indent=2))
    else:
        _print_human(payload)
        if normalized_command == "verify" and parsed_arguments.ci_mode:
            print(render_ci_report(payload=payload))

    if normalized_command == "verify" and parsed_arguments.ci_mode:
        return ci_exit_code(payload=payload)
    return 0 if result.status in {"OK", "INFO", "WARNING"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
