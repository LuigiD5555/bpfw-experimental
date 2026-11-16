"""Bounded, read-only relational authority diagnostics for Verify / Status."""
from __future__ import annotations
from pathlib import Path
from bpfw.reports.finding import Finding,FINDING_SEVERITY_BLOCK,FINDING_SEVERITY_WARNING


def sqlite_findings(project_root: Path, *, limit: int=100) -> list[Finding]:
    from .migration import active_backend
    if active_backend(project_root) != 'sqlite':
        return []
    from .store import SqliteAuthorityStore
    out = []
    try:
        store=SqliteAuthorityStore(project_root)
        with store.connect() as conn:
            for row in conn.execute("""SELECT c.uid,c.source_block_uid,c.target_literal
                                       FROM connections c WHERE c.target_literal IS NOT NULL
                                       AND c.target_literal!='' AND c.target_block_uid IS NULL LIMIT ?""",(limit,)):
                out.append(Finding(source='sqlite.authority',code='SQLITE_UNRESOLVED_CONNECTION',
                                   severity=FINDING_SEVERITY_WARNING,
                                   message=f"Connection {row['uid']} references an unknown block: {row['target_literal']}",
                                   evidence={'connection_uid':row['uid'],'source_block_uid':row['source_block_uid'],
                                             'target':row['target_literal']}))
            for row in conn.execute("""SELECT path,symbol,kind,COUNT(*) AS count FROM artifacts
                                    WHERE path IS NOT NULL AND path!=''
                                    GROUP BY path,symbol,kind HAVING COUNT(*)>1 LIMIT ?""",(limit,)):
                out.append(Finding(source='sqlite.authority',code='SQLITE_DUPLICATE_ARTIFACT_TARGET',
                                   severity=FINDING_SEVERITY_WARNING,
                                   message=f"Multiple artifacts refer to {row['path']}::{row['symbol']}",
                                   evidence={'path':row['path'],'symbol':row['symbol'],'count':row['count']}))
    except Exception as error:
        out.append(Finding(source='sqlite.authority',code='SQLITE_DATABASE_UNREADABLE',
                           severity=FINDING_SEVERITY_BLOCK,message=str(error),
                           evidence={'error_type':type(error).__name__}))
    return out
