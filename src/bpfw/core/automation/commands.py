"""CLI adapter for deterministic Blueprint Automation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from bpfw.core.automation.audit import audit_blueprint
from bpfw.core.automation.engine import AutomationEngine


def _mutation_parser(prog: str) -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, add_help=True)
    p.add_argument("--apply", action="store_true", help="Create and immediately apply the generated plan.")
    p.add_argument("--dry-run", action="store_true", help="Alias for plan-only mode (the default).")
    return p


def _emit(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, indent=2, ensure_ascii=False, default=str)); return
    if isinstance(value, dict) and value.get("schema") == "bpfw.automation.audit/v1":
        totals = value["totals"]; summary = value["summary"]
        print("Blueprint Automation Audit\n")
        print(f"Blocks:                 {totals['blocks']}")
        print(f"Artifacts:              {totals['artifacts']}")
        print(f"Invariants:             {totals['invariants']}")
        print(f"Connections:            {totals['connections']}\n")
        print(f"Missing UIDs:           {summary['missing_uids']}")
        print(f"Missing files:          {summary['missing_files']}")
        print(f"Unresolved symbols:     {summary['unresolved_symbols']}")
        print(f"Redundant fields:       {summary['redundant_fields']}")
        print(f"Unknown profiles:       {summary.get('unknown_profiles', 0)}")
        print(f"Unbound code units:     {summary['unbound_code_units']}")
        print(f"Unbound flow artifacts: {summary['unbound_flow_artifacts']}")
        print(f"Possible profiles:      {summary['possible_profiles']}")
        if value.get("possible_profiles"):
            print("\nProfile candidates:")
            for item in value["possible_profiles"][:10]: print(f"  {item['count']:>3}x  {item['fields']}")
        return
    if isinstance(value, dict) and value.get("plan_id"):
        print(f"Plan:       {value['plan_id']}")
        print(f"Operation:  {value.get('operation')}")
        print(f"Changes:    {value.get('change_count', 0)}")
        print(f"Before:     {str(value.get('before_digest', ''))[:16]}")
        print(f"After:      {str(value.get('after_digest', ''))[:16]}")
        print(f"Status:     {'APPLIED' if value.get('applied') else 'PLANNED'}")
        if not value.get("applied"):
            print(f"\nApply with:\n  bpfw batch apply {value['plan_id']}")
        changes = value.get("changes") or []
        if changes:
            print("\nPreview:")
            for change in changes[:12]:
                print(f"  {change.get('scope','')} {change.get('parent') or ''} {change.get('entity') or ''} :: {change.get('field')}")
            if len(changes) > 12: print(f"  ... {len(changes)-12} more")
        return
    print(value)


def _plan_or_apply(engine: AutomationEngine, operation: str, args: dict[str, Any], apply: bool, as_json: bool) -> int:
    plan = engine.create_plan(operation, args)
    if apply and plan.get("change_count"):
        plan = engine.apply_plan(str(plan["plan_id"]))
    _emit(plan, as_json)
    return 0


def run_automation_cli(command: str, subcommand: str | None, remaining: list[str], project_root: Path, as_json: bool) -> int:
    engine = AutomationEngine(project_root)
    if command == "batch":
        if subcommand == "audit":
            p = argparse.ArgumentParser(prog="bpfw batch audit")
            p.add_argument("--details", action="store_true", help="Include complete issue lists instead of compact samples.")
            p.add_argument("--limit", type=int, default=12, help="Maximum sample items per issue class in compact mode.")
            ns = p.parse_args(remaining)
            audit = audit_blueprint(project_root)
            if as_json and not ns.details:
                audit = {
                    "schema": audit["schema"], "authority_state": audit["authority_state"],
                    "totals": audit["totals"], "summary": audit["summary"],
                    "possible_profiles": audit.get("possible_profiles", [])[:10],
                    "samples": {key: values[:max(0, ns.limit)] for key, values in audit.get("issues", {}).items()},
                    "detail_hint": "Use bpfw batch audit --json --details or bpfw batch discover-artifacts --json for full lists.",
                }
            _emit(audit, as_json); return 0
        if subcommand == "discover-artifacts":
            p = argparse.ArgumentParser(prog="bpfw batch discover-artifacts"); p.add_argument("--unbound", action="store_true"); p.add_argument("--limit", type=int, default=200); ns=p.parse_args(remaining)
            audit = audit_blueprint(project_root)
            payload = {"code": audit["issues"]["unbound_code_units"][:ns.limit], "flow": audit["issues"]["unbound_flow_artifacts"][:ns.limit]}
            if as_json: _emit(payload, True)
            else:
                print("Unbound artifact candidates\n")
                print("Code:")
                for item in payload["code"]: print(f"  {item['language']:<8} {item['path']}::{item['symbol']} [{item['kind']}]")
                print("\nFlow artifacts:")
                for item in payload["flow"]: print(f"  {item['path']}  <- {item['referenced_by']}")
            return 0
        if subcommand == "apply":
            p=argparse.ArgumentParser(prog="bpfw batch apply"); p.add_argument("plan_id"); ns=p.parse_args(remaining)
            _emit(engine.apply_plan(ns.plan_id), as_json); return 0
        if subcommand == "generate-uids":
            p=_mutation_parser("bpfw batch generate-uids"); ns=p.parse_args(remaining)
            return _plan_or_apply(engine, "generate-uids", {}, ns.apply, as_json)
        if subcommand in {"set", "default", "remove", "rename-field", "replace-value"}:
            p=_mutation_parser(f"bpfw batch {subcommand}")
            p.add_argument("--scope", choices=["block","artifact","invariant","connection"], default="artifact")
            p.add_argument("--where", default=None, help="Simple field=value or field!=value selector.")
            p.add_argument("--field", required=True)
            if subcommand in {"set", "default"}: p.add_argument("--value", required=True)
            if subcommand == "rename-field": p.add_argument("--to", required=True)
            if subcommand == "replace-value": p.add_argument("--from", dest="from_value", required=True); p.add_argument("--to", required=True)
            ns=p.parse_args(remaining); args={"scope":ns.scope,"where":ns.where,"field":ns.field}
            if hasattr(ns,"value"): args["value"]=ns.value
            if subcommand == "rename-field": args["to"]=ns.to
            if subcommand == "replace-value": args.update({"from":ns.from_value,"to":ns.to})
            return _plan_or_apply(engine, subcommand, args, ns.apply, as_json)
        if subcommand == "move-path":
            p=_mutation_parser("bpfw batch move-path"); p.add_argument("from_path"); p.add_argument("to_path"); ns=p.parse_args(remaining)
            return _plan_or_apply(engine, "move-path", {"from":ns.from_path,"to":ns.to_path}, ns.apply, as_json)
        raise SystemExit("Unknown batch subcommand. Use audit, discover-artifacts, generate-uids, set, default, remove, rename-field, replace-value, move-path, or apply.")
    if command == "normalize":
        if subcommand is not None: remaining=[subcommand]+remaining
        p=_mutation_parser("bpfw normalize"); ns=p.parse_args(remaining)
        return _plan_or_apply(engine, "normalize", {}, ns.apply, as_json)
    if command == "compact":
        if subcommand is not None: remaining=[subcommand]+remaining
        p=_mutation_parser("bpfw compact"); p.add_argument("--min-occurrences", type=int, default=3); ns=p.parse_args(remaining)
        return _plan_or_apply(engine, "compact", {"min_occurrences":ns.min_occurrences}, ns.apply, as_json)
    return 1
