"""PURPOSE structural shapes for authority block containers
DOMAIN  blueprint files
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class BlockContainer(Protocol):
    """PURPOSE required shape for any object that holds and provides access to blueprint blocks
    DOMAIN  blueprint files
    """

    def get_blocks(self) -> list[dict[str, Any]]: ...