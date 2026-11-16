"""Compile BPFW evidence requirements into PipeCraft v1 pipelines."""
from __future__ import annotations
import hashlib
import re
from pathlib import Path
import yaml

from bpfw.core.evidence.models import EvidenceRequirement


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-").lower()
    return normalized or "evidence"

class PipeCraftEvidenceCompiler:
    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.workspace_root = self.project_root / ".bpfw" / "cache" / "pipecraft"

    def compile(self, requirement: EvidenceRequirement) -> tuple[str, Path]:
        if requirement.kind != "command" or not requirement.command:
            raise ValueError("Only structured command evidence can be compiled directly in this release.")
        identity = "\0".join(requirement.command).encode("utf-8")
        digest = hashlib.sha256(identity).hexdigest()[:10]
        suffix = f"-{requirement.scenario}" if requirement.scenario else ""
        name = _safe_name(f"bpfw-{requirement.invariant_id}{suffix}-{digest}")
        pipeline_dir = self.workspace_root / ".pipelines" / "pipelines"
        pipeline_dir.mkdir(parents=True, exist_ok=True)
        path = pipeline_dir / f"{name}.yaml"
        payload = {
            "schema_version": "pipecraft/v1",
            "name": name,
            "steps": [
                {
                    "id": "evidence",
                    "type": "command",
                    "with": {
                        "argv": list(requirement.command),
                        "cwd": str(self.project_root),
                    },
                }
            ],
        }
        path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
        return name, self.workspace_root
