"""Low-level mechanical patch primitives for Blueprint Engine.

This package is internal. It applies explicit operations to files under
``bpfw/`` after inspector, editor, planner, or a safe mechanical workflow has
already produced an approved change request.
"""

from bpfw.core.authority.patch.actions import (
    AddCoveredCodeOperation,
    AddIgnoreRuleOperation,
    CreateBlockOperation,
    CreateShardFileOperation,
    DeleteBlockOperation,
    DeleteShardFileOperation,
    MoveBlockOperation,
    MoveShardFileOperation,
    PatchOperation,
    PatchOperationKind,
    RemoveCoveredCodeOperation,
    RemoveIgnoreRuleOperation,
    RenameShardFileOperation,
    UpdateBlockCodeReferenceOperation,
    UpdateBlockLocationOperation,
    UpdateBlockMetadataOperation,
    UpdateBlockSymbolOperation,
)
from bpfw.core.authority.patch.engine import AuthorityPatchEngine
from bpfw.core.authority.patch.plan import AuthorityPatchPlan
from bpfw.core.authority.patch.result import AuthorityPatchResult
from bpfw.core.authority.patch.transaction import PatchWriteContext, TransactionBackup

__all__ = [
    "PatchOperationKind",
    "PatchOperation",
    "MoveBlockOperation",
    "CreateBlockOperation",
    "DeleteBlockOperation",
    "UpdateBlockMetadataOperation",
    "UpdateBlockLocationOperation",
    "UpdateBlockSymbolOperation",
    "UpdateBlockCodeReferenceOperation",
    "AddIgnoreRuleOperation",
    "AddCoveredCodeOperation",
    "RemoveIgnoreRuleOperation",
    "RemoveCoveredCodeOperation",
    "CreateShardFileOperation",
    "DeleteShardFileOperation",
    "RenameShardFileOperation",
    "MoveShardFileOperation",
    "AuthorityPatchPlan",
    "AuthorityPatchResult",
    "AuthorityPatchEngine",
    "PatchWriteContext",
    "TransactionBackup",
]
