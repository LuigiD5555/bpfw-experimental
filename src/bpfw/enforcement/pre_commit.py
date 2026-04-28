"""Pre-commit enforcement helpers for BPFW."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


class HookInstallError(RuntimeError):
    """Raised when git hook installation fails."""


def install_pre_commit_hook(project_root: Path) -> Path:
    """Install deterministic pre-commit and pre-push hooks for BPFW enforcement."""

    hooks_directory = project_root / ".git" / "hooks"
    if not hooks_directory.exists():
        raise HookInstallError(f"Git hooks directory not found: {hooks_directory}")

    installed_hook_path = hooks_directory / "pre-commit"
    for hook_name in ("pre-commit", "pre-push"):
        template_resource = resources.files("bpfw").joinpath(f"hooks/{hook_name}")
        try:
            hook_script = template_resource.read_text(encoding="utf-8")
        except OSError as error:
            raise HookInstallError(f"Cannot load bundled {hook_name} hook template") from error
        hook_path = hooks_directory / hook_name
        hook_path.write_text(hook_script, encoding="utf-8")
        hook_path.chmod(0o755)
        if hook_name == "pre-commit":
            installed_hook_path = hook_path
    return installed_hook_path
