"""Read-only export of the old wxauto prototype; never opens the new live database."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def export_legacy(source: Path, destination: Path):
    from app.local_session import reject_link_path
    from app.platforms.windows_security import apply_current_user_acl
    reject_link_path(source);reject_link_path(destination)
    if not source.is_file():
        raise ValueError('Legacy database does not exist')
    if destination.exists():
        raise FileExistsError('Choose a new export directory; existing files are never overwritten')
    destination.mkdir(mode=0o700,parents=True)
    if os.name=='nt':apply_current_user_acl(destination)
    # mode=ro deliberately includes committed WAL data; do not use immutable=1.
    with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        fields={row[1] for row in db.execute('PRAGMA table_info(messages)')}
        if not {'source_event_id','chat_name','sender','content','source_time'} <= fields:
            raise ValueError('This is not the supported legacy wxauto database schema')
        groups=[row[0] for row in db.execute('SELECT DISTINCT chat_name FROM messages ORDER BY chat_name')]
        entries=[]
        message_map=[]
        for group in groups:
            # Group names never become paths (including reserved names and traversal).
            filename='group-'+hashlib.sha256(group.encode()).hexdigest()[:24]+'.csv'
            rows=db.execute('SELECT source_event_id,source_time,sender,content,id FROM messages WHERE chat_name=? ORDER BY id',(group,))
            count=0
            with (destination/filename).open('x',encoding='utf-8-sig',newline='') as handle:
                writer=csv.writer(handle)
                writer.writerow(['source_message_id','timestamp','sender','content'])
                for row in rows:
                    external_id='legacy-'+hashlib.sha256(str(row[0]).encode()).hexdigest()
                    writer.writerow((external_id,row[1],row[2],row[3]));count+=1
                    message_map.append({'legacy_message_id':row[4],'source_message_id':external_id,'file':filename})
            entries.append({'group':group,'file':filename,'messages':count})
        tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        archive={}
        for table,query in (
            ('question_candidates','SELECT q.id,q.message_id,q.title,q.category,q.confidence,q.status,q.version,q.created_at,q.updated_at,m.source_event_id FROM question_candidates q JOIN messages m ON m.id=q.message_id ORDER BY q.id'),
            ('summaries','SELECT id,summary_date,content,question_count,confirmed_count,created_at,updated_at FROM summaries ORDER BY id')):
            if table in tables:archive[table]=[dict(row) for row in db.execute(query)]
        manifest={'format':1,'groups':entries,'review_history_file':'legacy-review-history.json','review_history_imported':False,'notice':'CSV contains original message text. Import into the app; do not open untrusted chat text as an Excel spreadsheet. Legacy reviews and summaries are archived separately, not converted into new tasks.'}
        (destination/'legacy-message-map.json').write_text(json.dumps(message_map,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (destination/'legacy-review-history.json').write_text(json.dumps(archive,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        (destination/'export-index.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for path in destination.iterdir():
        if os.name=='nt':apply_current_user_acl(path)
        else:path.chmod(0o600)
    return {'groups':len(entries),'messages':sum(e['messages'] for e in entries),'review_history_imported':False}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    try:print(json.dumps(export_legacy(args.database,args.output)))
    except (OSError,ValueError,sqlite3.Error) as exc:
        print('Legacy export failed: '+type(exc).__name__,file=sys.stderr);sys.exit(1)
