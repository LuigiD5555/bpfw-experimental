"""Internal authority patch engine for BPFW.

This package provides the AuthorityPatchEngine and supporting models
used by the future ``bpfw diff`` workflow. It is not part of the
public CLI and must not be invoked from read-only commands.

Workflow::

    bpfw verify       → detects drift
    bpfw diff         → user chooses actions (future)
    AuthorityPatchEngine → applies approved plan
"""

from bpfw.authority.patch.actions import (
    CreateBlockOperation,
    CreateShardFileOperation,
    DeleteBlockOperation,
    DeleteShardFileOperation,
    MoveBlockOperation,
    MoveShardFileOperation,
    PatchOperation,
    PatchOperationKind,
    RenameShardFileOperation,
    UpdateBlockMetadataOperation,
)
from bpfw.authority.patch.engine import AuthorityPatchEngine
from bpfw.authority.patch.plan import AuthorityPatchPlan
from bpfw.authority.patch.result import AuthorityPatchResult
from bpfw.authority.patch.transaction import PatchWriteContext, TransactionBackup

__all__ = [
    # Operations
    "PatchOperationKind",
    "PatchOperation",
    "MoveBlockOperation",
    "CreateBlockOperation",
    "DeleteBlockOperation",
    "UpdateBlockMetadataOperation",
    "CreateShardFileOperation",
    "DeleteShardFileOperation",
    "RenameShardFileOperation",
    "MoveShardFileOperation",
    # Core
    "AuthorityPatchPlan",
    "AuthorityPatchResult",
    "AuthorityPatchEngine",
    "PatchWriteContext",
    "TransactionBackup",
]