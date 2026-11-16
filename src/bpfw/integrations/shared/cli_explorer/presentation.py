"""Terminal-size-aware, injection-safe plain-text views for all CLI catalogues."""
from __future__ import annotations

import json
import re
import shutil
import unicodedata
from typing import Any, Iterable

# Terminal-control sequences originating from authority text must never be emitted.
_ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\)|.)')


def safe(value: Any) -> str:
    value = str(value) if value is not None else ''
    value = _ANSI.sub('', value)
    return ''.join(' ' if ch in '\n\r\t' or unicodedata.category(ch) in {'Cc','Cf','Cs'}
                   else ch for ch in value)


def width(value: str) -> int:
    result = 0
    for ch in value:
        if unicodedata.combining(ch) or ch in {'\u200d','\ufe0f'}:
            continue
        result += 2 if unicodedata.east_asian_width(ch) in {'W','F'} else 1
    return result


def fit(value: Any, columns: int) -> str:
    if columns < 1:
        return ''
    value = safe(value)
    if width(value) <= columns:
        return value
    if columns == 1:
        return '…'
    output = []
    size = 0
    for ch in value:
        step = width(ch)
        if size + step > columns - 1:
            break
        output.append(ch);size += step
    return ''.join(output)+'…'


def wrap_text(value: Any, columns: int) -> list[str]:
    """Wrap untrusted Unicode to display columns without terminal escape codes."""
    text=safe(value)
    columns=max(1,columns)
    if not text:return ['']
    lines=[];current='';used=0
    for ch in text:
        step=width(ch)
        if used+step>columns and current:
            lines.append(current);current='';used=0
        current+=ch;used+=step
    if current:lines.append(current)
    return lines


def terminal_width() -> int:
    return max(32, shutil.get_terminal_size((80,24)).columns)


# The adapter owns profiles, column captions and domain-specific details.
DEFAULT_PROFILES = {'default': ('uid', 'name')}



def catalogue(rows: Iterable[dict[str,Any]], *, columns: tuple[str,...] | None = None,
              mode: str = 'auto', max_width: int | None = None, heading: str = 'EXPLORER',
              start: int = 1, labels: dict[str,str] | None = None) -> str:
    """Always preserve row identity; switch to records when a table is too narrow."""
    labels = labels or {}
    rows = tuple(rows)
    columns = columns or DEFAULT_PROFILES['default']
    bound = max_width or terminal_width()
    bound = max(32,bound)
    lines = [fit(heading,bound), '─' * min(bound,60)]
    if mode == 'vertical' or (mode=='auto' and bound < 58):
        for i,row in enumerate(rows,start):
            lines.append(f'[{i}] '+fit(row.get('external_id') or row.get('uid'),bound-5))
            for field in columns:
                if field=='external_id':continue
                label = labels.get(field,field)
                lines.append(f'  {label}: '+fit(row.get(field,''),max(1,bound-len(label)-4)))
        return '\n'.join(lines)
    field_names = ('#',*columns)
    nfields = len(columns)
    indexw = max(3,len(str(max(1,start+len(rows)-1)))+1)
    remaining = bound - indexw - (nfields*2)
    # Drop only *display* columns when width is tight; information remains available in detail.
    visible = list(columns)
    while len(visible)>1 and remaining < len(visible)*8:
        visible.pop()
        remaining = bound-indexw-len(visible)*2
    widths = {}
    remaining = bound-indexw-len(visible)*2
    for k,field in enumerate(visible):
        min_for_rest = 8*(len(visible)-k-1)
        preferred = 38 if field == 'purpose' else 22 if field in {'external_id','name'} else 14
        w = max(8,min(preferred,remaining-min_for_rest))
        widths[field]=w
        remaining-=w
    if not visible:
        return '\n'.join(lines)
    lines.append(f"{'#':<{indexw}}"+'  '.join(fit(labels.get(c,c),widths[c]).ljust(widths[c]) for c in visible))
    lines.append('─'*min(bound, 60))
    for i,row in enumerate(rows,start):
        cells=[]
        for col in visible:
            val=fit(row.get(col,''),widths[col]);cells.append(val+' '*max(0,widths[col]-width(val)))
        lines.append(f'{i:<{indexw}}'+'  '.join(cells).rstrip())
    return '\n'.join(lines)


def details(block: dict[str,Any], *, revision: int, max_width: int | None = None,
            title: str = 'EXPLORER', fields: tuple[str,...] = ('uid','name'),
            sections: tuple[str,...] = (), footer: str = 'detail <field>   b back   q quit') -> str:
    bound=max_width or terminal_width()
    lines=[fit(title+' / '+str(block.get('name') or block.get('id') or block.get('uid') or 'record'),bound),
           '─'*min(bound,60)]
    for key in fields:
        if key in block:
            title=key.upper()+': '
            value=block[key]
            if isinstance(value,(dict,list)):
                value=json.dumps(value,ensure_ascii=False)
            # Long text remains available by section, not by table truncation.
            text=safe(value)
            if key=='purpose' and len(text)>bound:
                import textwrap
                lines.append('PURPOSE:')
                lines.extend('  '+piece for piece in textwrap.wrap(text,max(10,bound-3)))
            else:
                lines.append(fit(title+text,bound))
    lines.append(f'REVISION: {revision}')
    for key in sections:
        value=block.get(key)
        if isinstance(value,(list,dict)):
            lines.append(f'{key.upper()}: {len(value)} '+('entries' if isinstance(value,list) else 'fields'))
        elif key in block:
            lines.append(f'{key.upper()}: '+fit(value,bound-12))
    lines.append(footer)
    return '\n'.join(lines)


def render_value(label: str, value: Any, max_width: int | None = None) -> str:
    bound=max_width or terminal_width()
    dump = json.dumps(value,ensure_ascii=False,indent=2,default=str)
    lines=[fit(label.upper(),bound),'─'*min(bound,60)]
    for line in dump.splitlines():
        lines.extend(wrap_text(line,bound))
    return '\n'.join(lines)
