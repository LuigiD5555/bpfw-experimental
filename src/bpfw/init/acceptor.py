from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from bpfw.authority.state import AuthorityState, save_authority_state
from bpfw.integrity.manifest import write_manifest
from bpfw.security.keyring import ensure_local_hmac_key


@dataclass(slots=True)
class BaselineAcceptanceResult:
    """Represents the result of accepting a generated baseline."""

    blueprint_path: Path
    architecture_path: Path
    manifest_path: Path
    accepted: bool


class InitialBaselineAcceptor:
    """Accepts generated baseline files and seals the first protected state."""

    def accept(self, project_root: Path) -> BaselineAcceptanceResult:
        """Promote generated baseline files into protected project authority files."""
        ensure_local_hmac_key(project_root=project_root)
        generated_blueprint_path = project_root / "blueprint.generated.yaml"
        generated_architecture_path = project_root / "architecture.generated.yaml"

        if not generated_blueprint_path.exists():
            raise RuntimeError("Missing blueprint.generated.yaml. Run `bpfw init` first.")
        if not generated_architecture_path.exists():
            raise RuntimeError("Missing architecture.generated.yaml. Run `bpfw init` first.")

        blueprint_path = project_root / "blueprint.yaml"
        architecture_path = project_root / "architecture.yaml"
        shutil.copyfile(generated_blueprint_path, blueprint_path)
        shutil.copyfile(generated_architecture_path, architecture_path)

        bpfw_root = project_root / ".bpfw"
        for relative_directory in ["access_requests", "access_grants", "proposals", "audit"]:
            (bpfw_root / relative_directory).mkdir(parents=True, exist_ok=True)

        manifest_result = write_manifest(project_root=project_root)
        save_authority_state(
            project_root=project_root,
            state=AuthorityState(
                protection_enabled=True,
                os_lock_enabled=False,
                active_unlock_window=None,
                last_relock_at="",
            ),
        )

        return BaselineAcceptanceResult(
            blueprint_path=blueprint_path,
            architecture_path=architecture_path,
            manifest_path=manifest_result.manifest_path,
            accepted=True,
        )
