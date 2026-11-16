"""Unified BPFW change gate around human or agent commands."""
from __future__ import annotations
from pathlib import Path
import subprocess

from bpfw.core.catalog.loader import BlueprintLoader
from bpfw.core.catalog.verify import run_verify
from bpfw.core.change_detection import changed_paths, snapshot_project


def _render_impact(project_root: Path, paths: list[str]) -> None:
    if not paths:
        print("Change impact: no in-scope file changes detected.")
        return
    try:
        from bpfw.core.catalog.verify import scan_project_from_blueprint
        from bpfw.core.graph import ChangeImpactAnalyzer, SystemGraphBuilder
        load_result = BlueprintLoader(project_root=project_root).load()
        if load_result.domain_document is None or (load_result.domain_document.version or 1) < 2:
            print(f"Changed files: {len(paths)}")
            return
        scan_result = scan_project_from_blueprint(
            project_root=project_root,
            blueprint_data=load_result.data,
            domain_document=load_result.domain_document,
        )
        graph = SystemGraphBuilder().build(load_result.domain_document, scan_result=scan_result, project_root=project_root)
        impact = ChangeImpactAnalyzer(graph).analyze_paths(paths)
        print("BPFW change impact:")
        print(f"  changed files:      {len(paths)}")
        print(f"  changed components: {', '.join(impact.changed_components) or '-'}")
        print(f"  direct impact:      {', '.join(impact.direct) or '-'}")
        print(f"  transitive impact:  {', '.join(impact.transitive) or '-'}")
        print(f"  blast radius:       {'SYSTEMIC' if impact.systemic else 'LOCAL/TRANSITIVE'}")
        if impact.critical_components:
            print(f"  critical path:      {', '.join(impact.critical_components)}")
    except Exception as error:  # Impact explanation must not hide the canonical verify verdict.
        print(f"Change impact analysis unavailable: {error}")


def run_command_after_verify(project_root: Path, command: list[str]) -> int:
    """Run a child command between pre- and post-change BPFW verification gates."""
    project_root = project_root.resolve()
    _pre_report, verify_exit_code = run_verify(project_root=project_root)
    if verify_exit_code != 0:
        print("BPFW verify failed.")
        print("BPFW pre-verification failed.")
        print("Execution blocked.\n")
        print("Run:\n  bpfw verify\n")
        print("Fix the reported drift before running this command again.")
        return verify_exit_code

    before = snapshot_project(project_root)
    print("BPFW verify passed.")
    print("BPFW pre-verification passed.")
    print("Running command:")
    print(f"  {' '.join(command)}")

    try:
        completed_process = subprocess.run(command, cwd=project_root, check=False)
    except FileNotFoundError:
        print(f"Executable not found: {command[0]}")
        return 1

    after = snapshot_project(project_root)
    paths = changed_paths(before, after)
    _render_impact(project_root, paths)

    _post_report, post_exit_code = run_verify(project_root=project_root)
    if post_exit_code != 0:
        print("\nBPFW post-verification failed.")
        print("Change Gate: BLOCK")
        print("The command ran, but the resulting project state violates Blueprint authority or protected intent.")
        return post_exit_code

    print("\nBPFW post-verification passed.")
    print("Change Gate: PASS")
    return completed_process.returncode
