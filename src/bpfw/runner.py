"""PURPOSE command execution gate backed by the verify pipeline
DOMAIN  command safety
"""

from pathlib import Path
import subprocess

from bpfw.core.catalog.verify import run_verify


def run_command_after_verify(project_root: Path, command: list[str]) -> int:
    """PURPOSE run a child command only when bpfw verify passes
    DOMAIN  command safety
    """
    _report, verify_exit_code = run_verify(project_root=project_root.resolve())
    if verify_exit_code != 0:
        print("BPFW verify failed.")
        print("Execution blocked.\n")
        print("Run:")
        print("  bpfw verify\n")
        print("Fix the reported drift before running this command again.")
        return verify_exit_code

    print("BPFW verify passed.")
    print("Running command:")
    print(f"  {' '.join(command)}")

    try:
        completed_process = subprocess.run(command, cwd=project_root, check=False)
    except FileNotFoundError:
        print(f"Executable not found: {command[0]}")
        return 1
    return completed_process.returncode
