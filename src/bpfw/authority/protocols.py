"""Structural protocols for authority block containers."""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BlockContainer(Protocol):
    """Protocol for any object that holds and provides access to blueprint blocks.

    Both AuthorityDocument and AuthorityShard satisfy this protocol.
    Use it for type hints where either container is acceptable.
    """

    def get_blocks(self) -> list[dict[str, Any]]: ...