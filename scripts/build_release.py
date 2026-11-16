"""Rebuild the installable wheel from local sources and refresh release checksums."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile


def refresh_checksums(release_root: Path) -> None:
    """Hash distributable files while excluding generated development caches."""
    excluded_directories = {".aoa_cache", ".git", "__pycache__", ".pytest_cache", "build", "dist"}
    checksum_lines = []
    for source_path in sorted(release_root.rglob("*")):
        relative_path = source_path.relative_to(release_root)
        if not source_path.is_file() or relative_path.as_posix() == "SHA256SUMS":
            continue
        if any(part in excluded_directories or part.endswith(".egg-info") for part in relative_path.parts):
            continue
        digest = hashlib.sha256(source_path.read_bytes()).hexdigest()
        checksum_lines.append(f"{digest}  {relative_path.as_posix()}\n")
    (release_root / "SHA256SUMS").write_text("".join(checksum_lines), encoding="utf-8")


def main() -> None:
    release_root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix="bpfw-release-build-") as staging_directory:
        staging_root = Path(staging_directory)
        project_root = staging_root / "project"
        project_root.mkdir()
        shutil.copytree(
            release_root / "src", project_root / "src",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"),
        )
        for filename in ("pyproject.toml", "README.md", "LICENSE"):
            shutil.copy2(release_root / filename, project_root / filename)
        environment = dict(os.environ, SOURCE_DATE_EPOCH="315532800", PYTHONDONTWRITEBYTECODE="1")
        output_directory = staging_root / "wheels"
        subprocess.run(
            [sys.executable, "-m", "pip", "wheel", "--disable-pip-version-check", "--no-deps",
             "--no-build-isolation", "--wheel-dir", str(output_directory), str(project_root)],
            check=True, env=environment,
        )
        wheels = list(output_directory.glob("*.whl"))
        if len(wheels) != 1:
            raise RuntimeError("Expected exactly one rebuilt BPFW wheel")
        with zipfile.ZipFile(wheels[0]) as archive:
            for source_path in (project_root / "src" / "bpfw").rglob("*"):
                if source_path.is_file():
                    member_name = source_path.relative_to(project_root / "src").as_posix()
                    if archive.read(member_name) != source_path.read_bytes():
                        raise RuntimeError(f"Wheel does not match source: {member_name}")
        target = release_root / wheels[0].name
        if any(path.name != target.name for path in release_root.glob("*.whl")):
            raise RuntimeError("Release contains a different wheel; keep one installable version")
        temporary_target = release_root / (target.name + ".pending")
        shutil.copy2(wheels[0], temporary_target)
        temporary_target.replace(target)
    refresh_checksums(release_root)
    print(json.dumps({"wheel": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    main()
