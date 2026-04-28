"""Key provider abstractions for signing and verification."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


LOCAL_KEY_RELATIVE_PATH = ".bpfw/local_hmac_key"


class KeyProvider(Protocol):
    """Contract for key resolution backends."""

    def get_key(self, *, purpose: str, project_root: Path) -> str:
        """Resolve secret key material."""


def _key_file_path(project_root: Path) -> Path:
    return project_root / LOCAL_KEY_RELATIVE_PATH


def ensure_local_hmac_key(project_root: Path) -> str:
    """Ensure a stable local HMAC key exists and return it."""

    key_path = _key_file_path(project_root=project_root)
    key_path.parent.mkdir(parents=True, exist_ok=True)
    if key_path.exists():
        key_value = key_path.read_text(encoding="utf-8").strip()
        if key_value:
            return key_value
    key_value = secrets.token_hex(32)
    key_path.write_text(f"{key_value}\n", encoding="utf-8")
    os.chmod(key_path, 0o600)
    return key_value


@dataclass(slots=True, frozen=True)
class EnvKeyProvider:
    """Reads keys from environment variables only."""

    env_var_names: list[str]

    def get_key(self, *, purpose: str, project_root: Path) -> str:
        del purpose, project_root
        for env_var_name in self.env_var_names:
            key_value = os.getenv(env_var_name, "").strip()
            if key_value:
                return key_value
        return ""


@dataclass(slots=True, frozen=True)
class LocalFileKeyProvider:
    """Reads or creates local key file."""

    def get_key(self, *, purpose: str, project_root: Path) -> str:
        del purpose
        return ensure_local_hmac_key(project_root=project_root)


@dataclass(slots=True, frozen=True)
class CompositeKeyProvider:
    """Tries providers in order until one returns a key."""

    providers: tuple[KeyProvider, ...]

    def get_key(self, *, purpose: str, project_root: Path) -> str:
        for provider in self.providers:
            key_value = provider.get_key(purpose=purpose, project_root=project_root).strip()
            if key_value:
                return key_value
        return ""


def resolve_hmac_key(*, project_root: Path, purpose: str, env_var_names: list[str]) -> str:
    """Resolve key using configured provider chain."""

    provider = CompositeKeyProvider(providers=(EnvKeyProvider(env_var_names=env_var_names), LocalFileKeyProvider()))
    return provider.get_key(purpose=purpose, project_root=project_root)
