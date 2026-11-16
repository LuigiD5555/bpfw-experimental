"""Independent non-SQLite adapter demonstrating reuse for arbitrary datasets.

Read-only intentional: arbitrary data cannot silently acquire Blueprint writes.
Consumers can implement preview/apply with their own domain's transaction rules.
"""
from __future__ import annotations
from collections import Counter
import csv
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterable
from .models import ExplorerPage, ExplorerQuery


class MemoryExplorerAdapter:
    """Portable adapter for an external list of dictionaries, isolated by `identity`."""
    editable=frozenset()
    default_sort='uid'

    def __init__(self, rows: Iterable[dict[str,Any]], *, identity: str,
                 title: str='DATA / EXPLORER', key: str='uid',
                 profiles: dict[str,tuple[str,...]] | None=None) -> None:
        if not identity:raise ValueError('Source identity is required')
        self.identity=identity;self.title=title;self.key=key
        self._rows={}
        for row in rows:
            uid=str(row[key])
            if uid in self._rows:raise ValueError('Duplicate identity: '+uid)
            self._rows[uid]={**row,'uid':uid,'entity_revision':int(row.get('entity_revision',1))}
        self.fields=frozenset({'uid','entity_revision'} | {k for row in self._rows.values() for k in row})
        self.sortable=self.fields
        self.groupable=self.fields
        self.profiles=profiles or {'default': ('uid',*tuple(k for k in sorted(self.fields-{'uid','entity_revision'})[:2]))}
        self.labels={key:key.upper() for key in self.fields}
        self.detail_fields=tuple(sorted(self.fields))
        self.section_fields=tuple(k for k in sorted(self.fields) if any(isinstance(row.get(k),(list,dict)) for row in self._rows.values()))
        self._version=1

    def _matching(self, query: ExplorerQuery) -> list[dict[str,Any]]:
        if query.sort not in self.sortable:raise ValueError('Unknown sort column: '+query.sort)
        if any(field not in self.fields for field,_ in query.filters):raise ValueError('Unknown filter field')
        if not 1<=query.limit<=100:raise ValueError('Page size must be within 1..100')
        rows=[r for r in self._rows.values() if all(str(r.get(k,''))==v for k,v in query.filters)]
        if query.search:
            rows=[r for r in rows if query.search.casefold() in ' '.join(str(v) for v in r.values()).casefold()]
        def sort_key(row: dict[str,Any]) -> tuple[Any,...]:
            value=row.get(query.sort)
            if isinstance(value,(int,float)) and not isinstance(value,bool):
                return (False,0,float(value),row['uid'])
            return (value is None,1,str(value or ''),row['uid'])
        rows.sort(key=sort_key,reverse=query.descending)
        return rows

    def page(self, query: ExplorerQuery, after: Any | None=None) -> ExplorerPage:
        from hashlib import sha256
        import json
        fingerprint=sha256(json.dumps((query.filters,query.search,query.sort,query.descending,query.limit)).encode()).hexdigest()
        if after is None:position=0
        else:
            version,finger,position=after
            if version!=self._version or finger!=fingerprint:raise ValueError('Dataset changed since this page')
        rows=self._matching(query)
        chunk=rows[position:position+query.limit]
        next_cursor=(self._version,fingerprint,position+query.limit) if position+query.limit<len(rows) else None
        return ExplorerPage(tuple(dict(r) for r in chunk),next_cursor,next_cursor is not None)

    def get(self, identity: str) -> tuple[dict[str,Any],int] | None:
        row=self._rows.get(identity)
        return (dict(row),row['entity_revision']) if row is not None else None

    def resolve(self, identities: list[str]) -> list[dict[str,Any]]:
        if len(set(identities))!=len(identities):raise ValueError('Duplicate identities')
        rows=[]
        for identity in identities:
            if identity not in self._rows:raise ValueError('Unknown identity: '+identity)
            rows.append(dict(self._rows[identity]))
        return rows

    def matching(self, query: ExplorerQuery) -> list[dict[str,Any]]:
        rows=self._matching(query)
        if len(rows)>10000:raise ValueError('Selection exceeds 10000 records')
        return [dict(row) for row in rows]

    def facets(self, query: ExplorerQuery, field: str) -> list[tuple[Any,int]]:
        if field not in self.groupable:raise ValueError('Unknown group: '+field)
        counts=Counter(str(r.get(field,'')) for r in self._matching(query))
        return sorted(counts.items(),key=lambda x:(-x[1],x[0]))

    def relations(self, identity: str) -> Any:
        return {'message':'This dataset does not declare relations'}

    def history(self, identity: str) -> Any:
        return []

    def issues(self) -> Any:
        return {'records':len(self._rows),'duplicates':0}

    def preview(self, patches: list[dict[str,Any]]) -> Any:
        raise ValueError('This adapter is read-only')

    def apply(self, patches: list[dict[str,Any]]) -> Any:
        raise ValueError('This adapter is read-only')

    def inspect(self, identity: str, input_func: Callable[[str],str],output: Callable[[str],Any]) -> Any:
        raise ValueError('Inspector not provided by this adapter')

    def export(self, query: ExplorerQuery, fmt: str, destination: str) -> int:
        """Atomic bounded export; read-only adapters can still share export UI."""
        if fmt not in {'csv','json'}:raise ValueError('Invalid export format')
        path=Path(destination)
        if not path.parent.is_dir():raise FileNotFoundError('Export directory does not exist')
        if path.exists():raise FileExistsError(f'Export target already exists: {path}')
        rows=self.matching(query)
        columns=sorted({k for row in rows for k in row})
        fd,tempname=tempfile.mkstemp(prefix='.explorer-export-',dir=str(path.parent))
        try:
            with os.fdopen(fd,'w',encoding='utf-8',newline='') as file:
                if fmt=='json':
                    json.dump(rows,file,ensure_ascii=False,indent=2,default=str)
                else:
                    writer=csv.DictWriter(file,fieldnames=columns,extrasaction='ignore')
                    writer.writeheader()
                    for row in rows:
                        writer.writerow({k:("'"+v if isinstance(v,str) and v.lstrip().startswith(('=','+','-','@')) else v)
                                         for k,v in row.items()})
                file.flush();os.fsync(file.fileno())
            os.link(tempname,path)
        finally:
            if os.path.exists(tempname):os.unlink(tempname)
        return len(rows)
