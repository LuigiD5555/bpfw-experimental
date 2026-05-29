"""Shared shapes for authority block containers."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BlockContainer(Protocol):
    """Shape for any object that holds and provides access to blueprint blocks."""

    def get_blocks(self) -> list[dict[str, Any]]: ...