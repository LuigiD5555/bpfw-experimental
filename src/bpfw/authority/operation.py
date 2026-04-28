from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AuthorityOperation:
    """Represents a mechanical operation against an authority resource."""

    operation_id: str
    resource_id: str
    resource_path: str
    operation_type: str
    scope: str
    payload: dict[str, str]
