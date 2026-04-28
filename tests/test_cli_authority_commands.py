from __future__ import annotations

import pytest

from bpfw.cli import normalize_command


def test_authority_status_maps() -> None:
    assert normalize_command("authority", "status", None, None) == "authority_status"


def test_authority_unlock_maps() -> None:
    assert normalize_command("authority", "unlock", "blueprint", None) == "authority_unlock"


def test_authority_relock_maps() -> None:
    assert normalize_command("authority", "relock", None, None) == "authority_relock"


def test_authority_lock_maps() -> None:
    assert normalize_command("authority", "lock", None, None) == "authority_lock"


def test_authority_unlock_requires_target() -> None:
    with pytest.raises(ValueError, match="authority unlock requires a resource target"):
        normalize_command("authority", "unlock", None, None)


def test_watch_maps() -> None:
    assert normalize_command("watch", None, None, None) == "watch"
