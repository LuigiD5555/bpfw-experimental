"""JSON client for the private PipeCraft 1.6 process boundary."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from bpfw.runtime.pipecraft.errors import PipeCraftExecutionError
from bpfw.runtime.pipecraft.manager import PipeCraftRuntimeManager
from bpfw.runtime.pipecraft.models import PipeCraftResponse

class PipeCraftClient:
    def __init__(self, manager: PipeCraftRuntimeManager | None = None) -> None:
        self.manager = manager or PipeCraftRuntimeManager()

    def version(self) -> str:
        return self.manager.ensure_installed().version

    def _invoke(self, root: Path, args: list[str], *, expect_json: bool = True) -> PipeCraftResponse:
        runtime = self.manager.ensure_installed()
        command = [str(runtime.path), "--root", str(root.resolve()), *args]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        payload: dict[str, Any] = {}
        stdout = completed.stdout or ""
        if expect_json and stdout.strip():
            try:
                parsed = json.loads(stdout)
            except json.JSONDecodeError as error:
                raise PipeCraftExecutionError(
                    f"PipeCraft returned malformed JSON for {' '.join(args)}: {error}; stdout={stdout[:500]!r}"
                ) from error
            if not isinstance(parsed, dict):
                raise PipeCraftExecutionError("PipeCraft JSON response must be an object.")
            payload = parsed
        response = PipeCraftResponse(
            command=tuple(command),
            returncode=completed.returncode,
            payload=payload,
            stdout=stdout,
            stderr=completed.stderr or "",
        )
        return response

    def validate(self, root: Path, pipeline: str) -> PipeCraftResponse:
        return self._invoke(root, ["validate", pipeline, "--json"])

    def plan(self, root: Path, pipeline: str) -> PipeCraftResponse:
        return self._invoke(root, ["plan", pipeline, "--json"])

    def run(
        self,
        root: Path,
        pipeline: str,
        *,
        execute: bool = False,
        max_workers: int = 1,
    ) -> PipeCraftResponse:
        args = ["run", pipeline, "--max-workers", str(max(1, max_workers)), "--json"]
        if execute:
            args.append("--execute")
        return self._invoke(root, args)
    def run_many(
        self,
        root: Path,
        pipelines: list[str] | tuple[str, ...],
        *,
        execute: bool = False,
        max_workers: int = 4,
        max_pipelines: int = 4,
        max_tasks: int = 16,
    ) -> PipeCraftResponse:
        names = [str(name) for name in pipelines if str(name).strip()]
        if not names:
            raise ValueError("run_many requires at least one pipeline name.")
        args = [
            "run-many", *names,
            "--max-workers", str(max(1, max_workers)),
            "--max-pipelines", str(max(1, max_pipelines)),
            "--max-tasks", str(max(1, max_tasks)),
            "--json",
        ]
        if execute:
            args.append("--execute")
        return self._invoke(root, args)

