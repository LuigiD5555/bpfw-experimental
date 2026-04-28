"""Pre-commit enforcement helpers for BPFW."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


class HookInstallError(RuntimeError):
    """Raised when git hook installation fails."""


def install_pre_commit_hook(project_root: Path) -> Path:
    """Install deterministic pre-commit hook for BPFW enforcement."""

    hooks_directory = project_root / ".git" / "hooks"
    if not hooks_directory.exists():
        raise HookInstallError(f"Git hooks directory not found: {hooks_directory}")

    template_resource = resources.files("bpfw").joinpath("hooks/pre-commit")
    try:
        hook_script = template_resource.read_text(encoding="utf-8")
    except OSError as error:
        raise HookInstallError("Cannot load bundled pre-commit hook template") from error

    hook_path = hooks_directory / "pre-commit"
    hook_path.write_text(hook_script, encoding="utf-8")
    hook_path.chmod(0o755)
    return hook_path
