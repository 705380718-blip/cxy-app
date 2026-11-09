from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from datetime import datetime, timedelta, timezone

from pydantic import ValidationError

from .models import DecoderMessage, ImportPreview
from .service import iso, now_utc
from .work_items import DeliveryError, require_source

MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
CST = timezone(timedelta(hours=8))
TXT_HEADER = re.compile(r'^\[([^\]]+)\]\s*([^:：]+)[:：]\s*(.*)$')


def timestamp(value):
    parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=CST)
    return iso(parsed)


def parse_rows(data: ImportPreview):
    if len(data.content.encode('utf-8')) > MAX_BYTES:
        raise DeliveryError('import_too_large', '导入文件不能超过 2 MiB', 413)
    text = data.content.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')
    errors, raw_rows = [], []
    if data.format == 'csv':
        reader = csv.DictReader(io.StringIO(text), strict=True)
        required = {'source_message_id', 'timestamp', 'sender', 'content'}
        if not reader.fieldnames or not required.issubset(reader.fieldnames) or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise DeliveryError('csv_columns', 'CSV 必須含 source_message_id,timestamp,sender,content 四个唯一列')
        try:
            for row in reader:
                if None in row or any(row.get(key) is None for key in required):
                    errors.append({'line': reader.line_num, 'detail': 'CSV 列数不匹配'})
                else:
                    raw_rows.append({'line': reader.line_num, **{k:row[k] for k in required}})
                if len(raw_rows) + len(errors) > MAX_ROWS:
                    raise DeliveryError('import_too_many_rows', '一次最多导入 2000 条', 413)
        except csv.Error as exc:
            errors.append({'line': reader.line_num, 'detail': 'CSV 格式不合法，请检查引号'})
    else:
        current = None
        for lineno, line in enumerate(text.splitlines(), 1):
            match = TXT_HEADER.match(line)
            if match:
                current = {'line':lineno, 'source_message_id':'', 'timestamp':match[1], 'sender':match[2], 'content':match[3]}
                raw_rows.append(current)
            elif line.startswith('['):
                current = None
                errors.append({'line':lineno, 'detail':'时间头或发送人格式不合法'})
            elif current is not None:
                current['content'] += '\n' + line
            elif line.strip():
                if data.default_sender and data.default_timestamp:
                    # A pasted unstructured block is one message with explicitly supplied metadata.
                    current = {'line':lineno, 'source_message_id':'', 'timestamp':data.default_timestamp.isoformat(), 'sender':data.default_sender, 'content':line}
                    raw_rows.append(current)
                else:
                    errors.append({'line':lineno, 'detail':'缺少时间和发送人；请补齐默认值或使用 [时间] 发送人: 正文 格式'})
            if len(raw_rows) + len(errors) > MAX_ROWS:
                raise DeliveryError('import_too_many_rows', '一次最多导入 2000 条', 413)
    valid, seen_ids = [], set()
    for row in raw_rows:
        try:
            row['timestamp'] = timestamp(row['timestamp'])
            row['sender'] = row['sender'].strip()
            row['content'] = row['content'].strip()
            row['source_message_id'] = row['source_message_id'].strip()
            if not row['sender'] or not row['content'] or len(row['source_message_id']) > 200:
                raise ValueError('empty or oversized field')
            DecoderMessage(chat_name='validate', sender=row['sender'], content=row['content'], source_time=row['timestamp'])
            if row['source_message_id']:
                if row['source_message_id'] in seen_ids:
                    raise ValueError('duplicate external id')
                seen_ids.add(row['source_message_id'])
            valid.append(row)
        except (ValueError, ValidationError):
            errors.append({'line':row['line'], 'detail':'时间/发送人/正文格式不合法，或外部消息 ID 重复'})
    errors.sort(key=lambda r:r['line'])
    return valid, errors


class ImportService:
    def __init__(self, database, organizer):
        self.database, self.organizer = database, organizer

    def preview(self, data):
        rows, errors = parse_rows(data)
        if not rows:
            return {'id':None, 'rows':[], 'errors':errors, 'row_count':0, 'status':'invalid', 'possible_duplicates':0}
        normalized = [{k:v for k,v in row.items() if k != 'line'} for row in rows]
        digest = hashlib.sha256(json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            require_source(conn, data.project_source_id, 'import')
            cutoff = iso(now_utc() - timedelta(hours=24))
            conn.execute("UPDATE import_batches SET preview_json='[]',error_rows='[]',status='expired' WHERE status='preview' AND created_at<?", (cutoff,))
            old = conn.execute('SELECT * FROM import_batches WHERE project_source_id=? AND content_hash=?', (data.project_source_id,digest)).fetchone()
            if old and old['status'] == 'committed':
                result = json.loads(old['result_json'])
                return {'id':old['id'], 'rows':rows, 'errors':errors, 'row_count':len(rows), 'status':'committed', 'possible_duplicates':result.get('duplicates',0), 'result':result}
            if old:
                conn.execute("UPDATE import_batches SET preview_json=?,error_rows=?,row_count=?,status='preview',created_at=? WHERE id=?", (json.dumps(rows,ensure_ascii=False),json.dumps(errors,ensure_ascii=False),len(rows),iso(now_utc()),old['id']))
                batch_id = old['id']
            else:
                cur = conn.execute("INSERT INTO import_batches(project_source_id,content_hash,row_count,status,error_rows,preview_json,created_at) VALUES (?,?,?,'preview',?,?,?)", (data.project_source_id,digest,len(rows),json.dumps(errors,ensure_ascii=False),json.dumps(rows,ensure_ascii=False),iso(now_utc())))
                batch_id = cur.lastrowid
            possible = 0
            for row in rows:
                if not row['source_message_id'] and conn.execute('SELECT 1 FROM messages WHERE project_source_id=? AND sender=? AND source_time=? AND raw_content=? LIMIT 1', (data.project_source_id,row['sender'],row['timestamp'],row['content'])).fetchone():
                    possible += 1
        return {'id':batch_id,'rows':rows,'errors':errors,'row_count':len(rows),'status':'preview','possible_duplicates':possible,
                'period_start':min(r['timestamp'] for r in rows),'period_end':max(r['timestamp'] for r in rows)}

    def commit(self, batch_id, accept_valid_rows):
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            batch = conn.execute('SELECT * FROM import_batches WHERE id=?', (batch_id,)).fetchone()
            if not batch:
                raise DeliveryError('import_not_found','导入预览不存在',404)
            source = require_source(conn,batch['project_source_id'],'import')
            if batch['status'] == 'committed':
                previous = json.loads(batch['result_json'])
                return {**previous, 'inserted':0, 'reused':True}
            if batch['status'] != 'preview' or batch['created_at'] < iso(now_utc()-timedelta(hours=24)):
                raise DeliveryError('preview_expired','预览已过期，请重新预览',409)
            if json.loads(batch['error_rows']) and not accept_valid_rows:
                raise DeliveryError('invalid_rows','存在错误行；修正或明确选择仅导入有效行',409)
            messages = []
            for index, row in enumerate(json.loads(batch['preview_json'])):
                identity = ('external:' + row['source_message_id']) if row['source_message_id'] else f"batch:{batch['content_hash']}:{index}"
                external_hash = hashlib.sha256(identity.encode()).hexdigest()
                sid = f"import:{source['id']}:{external_hash}"
                existing = conn.execute('SELECT sender,source_time,raw_content FROM messages WHERE source_id=?', (sid,)).fetchone()
                if existing and tuple(existing) != (row['sender'],row['timestamp'],row['content']):
                    raise DeliveryError('external_id_conflict','同一外部消息 ID 对应不同正文/时间，请检查原文件',409)
                messages.append(DecoderMessage(source_id=sid,chat_name=source['source_key'],sender=row['sender'],content=row['content'],source_time=row['timestamp'],source_kind='import'))
            result = self.organizer.ingest_many(messages, connection=conn, project_source_id=source['id'], import_batch_id=batch_id)
            result.pop('results')
            result.update({'batch_id':batch_id,'project_source_id':source['id'],'reused':False})
            conn.execute("UPDATE import_batches SET status='committed',preview_json='[]',result_json=? WHERE id=?", (json.dumps(result),batch_id))
            conn.execute('INSERT INTO audit_log(action,detail_json,created_at) VALUES (?,?,?)', ('delivery_import',json.dumps(result),iso(now_utc())))
            return result
