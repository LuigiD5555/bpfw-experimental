"""Opt-in SQLite authority CLI; no side effects for plan/preview commands."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .batch import export_blocks, import_csv
from .migration import active_backend, migrate_legacy
from .store import SqliteAuthorityStore


def _print_result(payload: object, *, as_json: bool) -> None:
    if as_json or isinstance(payload, (dict, list)):
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(payload)


def run_sqlite_cli(command: str, subcommand: str | None, tokens: list[str],
                   project_root: Path, as_json: bool) -> int:
    if command == "migrate":
        p = argparse.ArgumentParser(prog="bpfw migrate")
        p.add_argument("--to", choices=["sqlite"], required=True)
        group = p.add_mutually_exclusive_group()
        group.add_argument("--plan", action="store_true")
        group.add_argument("--apply", action="store_true")
        opts = p.parse_args(([subcommand] if subcommand else []) + tokens)
        output = migrate_legacy(project_root, apply=opts.apply)
        _print_result(output, as_json=as_json)
        return 0 if output["can_activate"] else 1

    if active_backend(project_root) != "sqlite":
        raise ValueError("SQLite authority is not active. Use bpfw migrate --to sqlite --plan first.")
    store = SqliteAuthorityStore(project_root)
    if command in {"lock", "unlock"}:
        from bpfw.core.protection.os_lock import verify_unlock_permission
        if command == "unlock" and store.locked() and not verify_unlock_permission():
            raise ValueError("Unlock authentication failed")
        store.set_locked(command == "lock")
        _print_result({"backend": "sqlite", "status": "locked" if store.locked() else "unlocked",
                       "protection": "logical guard; not OS immutable"}, as_json=as_json)
        return 0
    if command == "authority":
        p = argparse.ArgumentParser(prog="bpfw authority")
        p.add_argument("action", choices=["info", "doctor", "backup", "export", "restore"])
        p.add_argument("--out", type=Path)
        p.add_argument("--input", type=Path)
        p.add_argument("--apply", action="store_true")
        p.add_argument("--expected-revision", type=int)
        opts = p.parse_args(([subcommand] if subcommand else []) + tokens)
        if opts.action == "doctor":
            result = store.doctor()
            _print_result(result, as_json=as_json)
            return 0 if result["ok"] else 1
        if opts.action == "info":
            with store.connect() as conn:
                counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                          for table in ("blocks", "artifacts", "invariants", "connections", "outbox_events")}
            _print_result({"backend": "sqlite", "revision": store.revision(),
                           "database_bytes": store.path.stat().st_size, "counts": counts}, as_json=as_json)
            return 0
        if opts.action == 'export':
            if not opts.out: p.error('export requires --out PATH')
            if opts.out.exists(): raise FileExistsError(f'Export already exists: {opts.out}')
            opts.out.parent.mkdir(parents=True,exist_ok=True)
            from bpfw.core.atomic_io import atomic_write_text
            atomic_write_text(opts.out, json.dumps(store.load_document(), ensure_ascii=False,
                                                   sort_keys=True, indent=2) + '\n')
            _print_result({'exported': str(opts.out), 'revision':store.revision()},as_json=as_json)
            return 0
        if opts.action == 'restore':
            if not opts.input: p.error('restore requires --input PATH')
            from bpfw.core.authority.sqlite.store import digest
            payload=json.loads(opts.input.read_text(encoding='utf-8'))
            if not isinstance(payload,dict) or not isinstance(payload.get('blocks'),list):
                raise ValueError('Invalid authority snapshot JSON')
            current=store.load_document()
            result={'changed':digest(current)!=digest(payload),'current_revision':store.revision(),
                    'current_blocks':len(current.get('blocks',[])),'snapshot_blocks':len(payload['blocks'])}
            if opts.apply and result['changed']:
                import uuid
                backup=project_root/'.bpfw'/'backups'/('authority-before-restore-'+uuid.uuid4().hex+'.sqlite')
                store.backup(backup)
                from bpfw.core.blueprint_engine.engine import BlueprintEngine
                result['revision']=BlueprintEngine(project_root).replace_authority_document(
                    payload,reason='explicit snapshot restore',expected_revision=opts.expected_revision if opts.expected_revision is not None else result['current_revision'])
                result['backup']=str(backup)
                result['applied']=True
            else:
                result['applied']=False
            _print_result(result,as_json=as_json)
            return 0
        if not opts.out:
            p.error("backup requires --out PATH")
        store.backup(opts.out)
        _print_result({"backup": str(opts.out)}, as_json=as_json)
        return 0

    if command == "editor":
        p = argparse.ArgumentParser(prog="bpfw editor")
        p.add_argument("--view", choices=["table", "auto", "compact", "vertical"], default="auto")
        p.add_argument("--domain")
        p.add_argument("--status")
        p.add_argument("--search")
        p.add_argument("--limit", type=int, default=50)
        p.add_argument("--select", action="append", help="Block UID or ID (repeatable)")
        p.add_argument("--all", action="store_true", help="Select matching rows up to --limit")
        p.add_argument("--set", action="append", default=[], metavar="FIELD=VALUE")
        p.add_argument("--clear", action="append", default=[], metavar="FIELD")
        p.add_argument("--apply", action="store_true")
        p.add_argument("--interactive", action="store_true")
        opts = p.parse_args(([subcommand] if subcommand else []) + tokens)
        from .editor import run_editor
        # The default terminal session is interactive only when both streams are TTYs.
        # JSON and piped output never prompt, clear the screen or print banners.
        auto_interactive = (not as_json and sys.stdin.isatty() and sys.stdout.isatty()
                            and not (opts.select or opts.all or opts.set or opts.clear or opts.apply))
        if opts.interactive and as_json:
            p.error("--json and --interactive are mutually exclusive")
        interactive=opts.interactive or auto_interactive
        result = run_editor(store, domain=opts.domain, status=opts.status, search=opts.search,
                            limit=opts.limit, selected=opts.select, all_matching=opts.all,
                            assignments=opts.set, clears=opts.clear,apply=opts.apply,
                            interactive=interactive, view=opts.view)
        if interactive:
            return 0
        if as_json or not result.get('read_only'):
            _print_result(result, as_json=True)
        else:
            from bpfw.integrations.shared.cli_explorer.presentation import catalogue
            from .explorer_adapter import BpfwExplorerAdapter
            mode = 'compact' if opts.view == 'table' else opts.view
            print(catalogue(result.get('rows',[]),mode=mode,
                            columns=BpfwExplorerAdapter.profiles['responsibilities'],
                            labels=BpfwExplorerAdapter.labels,heading=BpfwExplorerAdapter.title))
            print('Read-only catalogue. Use --interactive in a terminal or --select/--all --set field=value.')
        return 0

    if command == "batch":
        p = argparse.ArgumentParser(prog="bpfw batch")
        p.add_argument("action", choices=["export", "import"])
        p.add_argument("filename", nargs="?")
        p.add_argument("--scope", default="block", choices=["block"])
        p.add_argument("--format", default="csv", choices=["csv"])
        p.add_argument("--out", type=Path)
        p.add_argument("--domain")
        group = p.add_mutually_exclusive_group()
        group.add_argument("--apply", action="store_true")
        group.add_argument("--dry-run", action="store_true")
        opts = p.parse_args(([subcommand] if subcommand else []) + tokens)
        if opts.action == "export":
            if not opts.out:
                p.error("export requires --out PATH")
            total = export_blocks(store, opts.out, domain=opts.domain)
            _print_result({"exported": total, "file": str(opts.out)}, as_json=as_json)
            return 0
        if not opts.filename:
            p.error("import requires a CSV path")
        result = import_csv(store, Path(opts.filename), apply=opts.apply)
        _print_result({**result, "applied": bool(opts.apply)}, as_json=as_json)
        return 0
    raise ValueError(f"Unsupported SQLite CLI command: {command}")
