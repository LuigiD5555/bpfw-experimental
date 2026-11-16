"""Reusable command-driven CLI explorer. No BPFW/SQLite/Blueprint imports.

The adapter supplies data and domain actions. Controller owns only transient,
per-session navigation state, generic selection and explicit user confirmation.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import shlex
from typing import Any, Callable

from .models import ExplorerAdapter, ExplorerQuery
from .presentation import catalogue, details, render_value, safe


def parsed_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def selection_indices(spec: str, size: int) -> list[int]:
    """One-based indices for the *visible page*. '*' never selects all pages."""
    if not spec:
        raise ValueError('Supply row numbers, ranges or all')
    if spec in {'*','page'}:
        return list(range(size))
    result: set[int] = set()
    for item in spec.replace(' ', ',').split(','):
        if not item:
            continue
        if '-' in item:
            part=item.split('-')
            if len(part)!=2 or not all(x.isdigit() for x in part):
                raise ValueError(f'Invalid selection range: {item}')
            first,last=map(int,part)
            if first>last:
                raise ValueError('Selection ranges must be ascending')
            if last-first>10000:
                raise ValueError('Selection exceeds safety limit')
            result.update(range(first-1,last))
        elif item.isdigit():
            result.add(int(item)-1)
        else:
            raise ValueError(f'Invalid selection index: {item}')
        if len(result)>10000:
            raise ValueError('Selection exceeds safety limit')
    if any(x<0 or x>=size for x in result):
        raise ValueError('Selection index is outside the current page')
    return sorted(result)


@dataclass
class BrowserState:
    query: ExplorerQuery = field(default_factory=ExplorerQuery)
    position: Any | None = None
    pages: list[Any | None] = field(default_factory=lambda:[None])
    detail_uid: str | None = None
    selected: dict[str,int] = field(default_factory=dict)
    pending: list[dict[str,Any]] = field(default_factory=list)
    reviewed: bool = False
    mode: str = 'auto'
    profile: str = ''
    columns: tuple[str,...] = ()
    notice: str = ''


class BrowserController:
    def __init__(self, adapter: ExplorerAdapter, *, input_func: Callable[[str],str]=input,
                 output: Callable[[str],Any]=print, page_size: int=20,
                 query: ExplorerQuery | None=None) -> None:
        self.adapter=adapter
        self.input=input_func
        self.output=output
        if not adapter.profiles:
            raise ValueError('Adapter must define at least one column profile')
        profile=next(iter(adapter.profiles))
        self.state=BrowserState(query=query or ExplorerQuery(limit=page_size,sort=adapter.default_sort),
                                profile=profile,columns=adapter.profiles[profile])
        self._page=None
        self._detail=None
        # Session data has no process-global cache and belongs only to this adapter.

    def notify(self, text: str) -> None:
        self.state.notice=text

    def reset_pagination(self) -> None:
        self.state.position=None
        self.state.pages=[None]
        self._page=None

    def refresh(self) -> None:
        try:
            self._page=self.adapter.page(self.state.query,after=self.state.position)
        except ValueError as exc:
            if not self.state.position:
                raise
            self.reset_pagination()
            self._page=self.adapter.page(self.state.query)
            self.notify('Dataset changed: catalogue restarted; selections retain their original revisions. '+str(exc))

    def render(self) -> None:
        if self.state.detail_uid:
            hit=self.adapter.get(self.state.detail_uid)
            if not hit:
                self.state.detail_uid=None
                self.notify('Selected record was removed; returning to catalogue.')
            else:
                self._detail=hit
                self.output(details(hit[0],revision=hit[1],title=self.adapter.title,
                                    fields=self.adapter.detail_fields,
                                    sections=tuple(k for k in self.adapter.section_fields if k in hit[0]),
                                    footer='detail <field>  relations  '+
                                    ('edit <field>=<value>  ' if self.adapter.editable else '')+
                                    'b back  q quit'))
                if self.state.notice:
                    self.output(self.state.notice);self.state.notice=''
                return
        self.refresh()
        self.output(catalogue(self._page.rows,columns=self.state.columns,mode=self.state.mode,
                              heading=self.adapter.title+' | page '+str(len(self.state.pages))+
                              ' | selected '+str(len(self.state.selected)),labels=dict(self.adapter.labels)))
        self.output(('More results → [n]   ' if self._page.has_next else '')+
                    '[p] previous  [/] search  [f] filter  [m] select  [cols]  [?] help')
        if self.state.notice:
            self.output(self.state.notice);self.state.notice=''

    def _parse(self, value: str) -> tuple[str,str]:
        raw=value.strip()
        if not raw:return '', ''
        if raw.startswith('/'):return 'search',raw[1:].strip()
        if raw.isdigit():return 'open',raw
        command,_,payload=raw.partition(' ')
        cmd={'?':'help','h':'help','q':'quit','b':'back','n':'next','p':'prev',
             'm':'select','by':'group','f':'filter','selection':'selected'}.get(command.lower(),command.lower())
        return cmd,payload.strip()

    def _visible(self, number: str) -> dict[str,Any]:
        if self._page is None:self.refresh()
        if number.isdigit():
            index=int(number)-1
            if not 0<=index<len(self._page.rows):
                raise ValueError('Row number is not on this page')
            return self._page.rows[index]
        return self.adapter.resolve([number])[0]

    def _selection(self, spec: str) -> None:
        if spec in {'clear','none'}:
            self.state.selected.clear();self.state.pending.clear();self.state.reviewed=False
            self.notify('Selection cleared')
            return
        if spec=='all':
            rows=self.adapter.matching(self.state.query)
        elif spec.startswith('uid '):
            rows=self.adapter.resolve(spec[4:].replace(',',' ').split())
        else:
            if self._page is None:self.refresh()
            rows=[self._page.rows[i] for i in selection_indices(spec,len(self._page.rows))]
        for row in rows:self.state.selected[row['uid']]=int(row['entity_revision'])
        self.state.reviewed=False
        self.notify(f'Selected {len(rows)} record(s); {len(self.state.selected)} in set.')

    def _targets(self) -> dict[str,int]:
        if self.state.detail_uid:
            # Read revision afresh from provider: it is used for optimistic locking.
            record=self.adapter.get(self.state.detail_uid)
            if record is None:raise ValueError('Selected record no longer exists')
            return {self.state.detail_uid:record[1]}
        if self.state.selected:return dict(self.state.selected)
        raise ValueError('Select rows with m first, or open a record')

    def _append_patch(self, path: str, operation: str, value: Any=None) -> None:
        if path not in self.adapter.editable:
            raise ValueError('Field is not editable: '+path)
        targets=self._targets()
        if len(targets)*(1+len(self.state.pending))>100000:
            raise ValueError('Maximum 100000 pending cell operations')
        for uid,revision in targets.items():
            self.state.pending.append({'uid':uid,'expected_entity_revision':revision,
                                       'field':path,'op':operation,'value':value})
        self.state.reviewed=False
        self.notify(f'Prepared {len(targets)} {operation} operation(s) on {path}; review before apply.')

    def _review(self) -> None:
        if not self.state.pending:raise ValueError('No changes prepared')
        result=self.adapter.preview(self.state.pending)
        self.output(render_value('REVIEW — nothing has been saved',result))
        self.state.reviewed=True

    def _commit(self) -> None:
        if not self.state.reviewed:raise ValueError('Run review first; commit never occurs implicitly')
        if self.input('Type APPLY to commit all changes: ').strip()!='APPLY':
            self.notify('Cancelled; no changes were saved.');return
        result=self.adapter.apply(self.state.pending)
        self.output(render_value('COMMITTED',result))
        self.state.pending.clear();self.state.reviewed=False;self.state.selected.clear()
        self.reset_pagination();self._detail=None

    def help(self) -> str:
        return (self.adapter.title+' — commands\n'
                'open 2 | open <uid> | 2 | b/back | q/quit | n/next | p/prev | first\n'
                '/ text | search text | f field=value | f list | f remove N | f clear\n'
                'sort <field> [asc|desc] | group <field> | cols | cols <profile>\n'
                'cols set field,field | view auto|compact|vertical\n'
                'm 1,3,5-8 | m uid <uid> | m all | m clear | selected\n'
                'edit field=value | clear field | review | apply\n'
                'detail <field> | relations | history | issues | inspect (if available)\n'
                'export csv|json <file> | ? help\n'
                'Rows are numbered PER PAGE; selection retains UID and revision.')

    def command(self, text: str) -> bool:
        cmd,arg=self._parse(text)
        if not cmd:return True
        if cmd=='quit':
            if self.state.pending and self.input('Discard pending (uncommitted) changes? [y/N]: ').strip().lower() not in {'y','yes'}:
                return True
            return False
        if cmd=='help':self.output(self.help());return True
        if cmd=='back':
            if self.state.detail_uid:self.state.detail_uid=None;self._detail=None
            elif len(self.state.pages)>1:
                self.state.pages.pop();self.state.position=self.state.pages[-1]
            else:self.notify('Already at catalogue root')
            return True
        if cmd in {'next','prev','first'}:
            if self.state.detail_uid:raise ValueError('Return to catalogue with b first')
            if cmd=='first':self.reset_pagination()
            elif cmd=='prev':
                if len(self.state.pages)>1:self.state.pages.pop();self.state.position=self.state.pages[-1]
                else:self.notify('Already on first page')
            elif self._page and self._page.has_next:
                self.state.pages.append(self._page.next_cursor)
                self.state.position=self._page.next_cursor
            else:self.notify('Already on last page')
            return True
        if cmd=='open':
            row=self._visible(arg);self.state.detail_uid=row['uid'];self._detail=None
            return True
        if cmd=='search':
            self.state.query=replace(self.state.query,search=arg)
            self.reset_pagination();return True
        if cmd=='filter':
            if arg in {'','list'}:
                self.output('Filters: '+safe(list(enumerate(self.state.query.filters,1)) or 'none'))
            elif arg=='clear':
                self.state.query=replace(self.state.query,filters=());self.reset_pagination()
            elif arg.startswith('remove '):
                index=int(arg.split()[1])-1
                if not 0<=index<len(self.state.query.filters):raise ValueError('Unknown filter number')
                fs=list(self.state.query.filters);fs.pop(index)
                self.state.query=replace(self.state.query,filters=tuple(fs));self.reset_pagination()
            elif '=' in arg:
                key,val=arg.split('=',1);key=key.strip()
                if key not in self.adapter.fields:raise ValueError('Unknown filter field: '+key)
                self.state.query=replace(self.state.query,filters=(*self.state.query.filters,(key,val)))
                self.reset_pagination()
            else:raise ValueError('Use f field=value, f list, f remove N, or f clear')
            return True
        if cmd=='sort':
            parts=arg.split()
            if not parts or len(parts)>2 or parts[0] not in self.adapter.sortable or (len(parts)==2 and parts[1] not in {'asc','desc'}):
                raise ValueError('Use sort <field> [asc|desc]')
            self.state.query=replace(self.state.query,sort=parts[0],descending=len(parts)==2 and parts[1]=='desc')
            self.reset_pagination();return True
        if cmd=='group':
            if arg not in self.adapter.groupable:raise ValueError('Cannot group by '+arg)
            for value,count in self.adapter.facets(self.state.query,arg):
                self.output(f'{safe(value or "(unset)")}: {count}')
            return True
        if cmd=='view':
            if arg not in {'auto','compact','vertical'}:raise ValueError('Use view auto|compact|vertical')
            self.state.mode=arg;return True
        if cmd=='cols':
            if not arg:
                self.output('Profiles: '+', '.join(self.adapter.profiles)+'\nColumns: '+', '.join(self.state.columns))
            elif arg in self.adapter.profiles:
                self.state.profile=arg;self.state.columns=self.adapter.profiles[arg]
            elif arg.startswith('set '):
                fields=tuple(x.strip() for x in arg[4:].split(','))
                if not fields or any(x not in self.adapter.fields for x in fields):raise ValueError('Unknown column')
                self.state.columns=fields
            else:raise ValueError('Unknown profile. Use cols for profiles, or cols set field,field')
            return True
        if cmd=='select':self._selection(arg);return True
        if cmd=='selected':
            self.output('Selected: '+str(len(self.state.selected)))
            for uid,rev in list(self.state.selected.items())[:30]:self.output(f'  {safe(uid)} @ {rev}')
            if len(self.state.selected)>30:self.output(f'  ... {len(self.state.selected)-30} more')
            return True
        if cmd=='edit':
            if '=' not in arg:raise ValueError('Use edit field=value')
            field,raw=arg.split('=',1);self._append_patch(field.strip(),'set',parsed_value(raw))
            return True
        if cmd=='clear':self._append_patch(arg,'clear');return True
        if cmd=='review':self._review();return True
        if cmd=='apply':self._commit();return True
        if cmd=='inspect':
            if not self.state.detail_uid:raise ValueError('Open a record first')
            if self.state.pending:raise ValueError('Review/apply/discard pending edits before inspecting')
            prior=self.adapter.get(self.state.detail_uid)
            if prior is None:raise ValueError('Record no longer exists')
            result=self.adapter.inspect(self.state.detail_uid,self.input,self.output)
            current=self.adapter.get(self.state.detail_uid);self._detail=current
            if current is None:
                self.state.detail_uid=None;self.reset_pagination();self.notify('Inspector removed record')
            elif current[1]!=prior[1]:
                self.reset_pagination();self.notify('Record changed: previous selections may be stale.')
            elif result=='error':self.notify('Inspector could not open record')
            return True
        if cmd=='detail':
            if not self.state.detail_uid:raise ValueError('Open a record first')
            hit=self.adapter.get(self.state.detail_uid)
            if hit is None:raise ValueError('Record no longer exists')
            if arg not in hit[0]:raise ValueError('No such field: '+arg)
            self.output(render_value(arg,hit[0][arg]));return True
        if cmd in {'relations','impact'}:
            if not self.state.detail_uid:raise ValueError('Open a record first')
            self.output(render_value('relations / impact',self.adapter.relations(self.state.detail_uid)))
            return True
        if cmd=='history':
            if not self.state.detail_uid:raise ValueError('Open a record first')
            self.output(render_value('history',self.adapter.history(self.state.detail_uid)));return True
        if cmd=='issues':self.output(render_value('issues',self.adapter.issues()));return True
        if cmd=='export':
            parts=shlex.split(arg)
            if len(parts)!=2 or parts[0] not in {'csv','json'}:raise ValueError('Use export csv|json <file>')
            count=self.adapter.export(self.state.query,*parts)
            self.notify(f'Exported {count} records to {parts[1]}')
            return True
        raise ValueError(f'Unknown command: {safe(cmd)} (try ?)')

    def run(self) -> None:
        while True:
            self.render()
            try:raw=self.input('explorer> ')
            except (EOFError,KeyboardInterrupt):
                if self.state.pending:self.output('Uncommitted edits discarded on terminal exit.')
                return
            try:
                if not self.command(raw):return
            except (ValueError,RuntimeError,FileNotFoundError,PermissionError) as exc:
                self.output('Cannot continue: '+safe(exc))
