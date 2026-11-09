"""Shared export escaping and project-scoped pseudonyms."""
from __future__ import annotations

import csv
import io
import re

from .ai.context import redact


def project_aliases(conn, project_id):
    names={r[0] for r in conn.execute('SELECT DISTINCT m.sender FROM messages m JOIN project_sources s ON s.id=m.project_source_id WHERE s.project_id=?',(project_id,))}
    names.update(r[0] for r in conn.execute("SELECT DISTINCT m.quote_sender FROM messages m JOIN project_sources s ON s.id=m.project_source_id WHERE s.project_id=? AND m.quote_sender!=''",(project_id,)))
    names.update(r[0] for r in conn.execute('SELECT DISTINCT w.owner FROM work_items w JOIN project_sources s ON s.id=w.project_source_id WHERE s.project_id=? AND w.owner IS NOT NULL',(project_id,)))
    aliases={name:f'成员{index+1}' for index,name in enumerate(sorted(names)) if name}
    for source in conn.execute('SELECT * FROM project_sources WHERE project_id=?',(project_id,)):
        for value in (source['source_key'],source['display_name']):
            if value:aliases[value]=f"来源{source['id']}"
    project=conn.execute('SELECT name FROM projects WHERE id=?',(project_id,)).fetchone()
    if project:aliases[project[0]]=f'项目{project_id}'
    return aliases


def safe_text(value, aliases):
    text=redact(value,aliases)
    # Cover IPv6 loopback and more credential/password forms in free-form exports.
    text=re.sub(r'(?i)(?:api[_ -]?key|token|password|密码|密钥)\s*[:=：]\s*[^\s，。；]+','[凭据已脱敏]',text)
    return text.replace('::1','[已脱敏]')


def markdown_text(value):
    # Markdown downloads may be opened by an HTML-capable viewer. Escape raw HTML/links.
    text=str(value or '').replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
    return re.sub(r'([\\`*_{}\[\]()#!|])',r'\\\1',text).replace('\r','').replace('\n',' / ')


def csv_text(headers, rows):
    stream=io.StringIO(newline='');writer=csv.writer(stream,lineterminator='\r\n')
    writer.writerow(headers)
    for row in rows:
        cells=[]
        for value in row:
            cell='' if value is None else str(value)
            if cell.lstrip().startswith(('=','+','-','@')) or cell.startswith(('\t','\r','\n')):
                cell="'"+cell
            cells.append(cell)
        writer.writerow(cells)
    return '\ufeff'+stream.getvalue()
