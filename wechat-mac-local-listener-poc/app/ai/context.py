"""Fixed, source-scoped context. Only display text enters the cloud payload."""
from __future__ import annotations

import hashlib
import json
import re

from ..work_items import DeliveryError, require_source
from .prompts import PROMPT_VERSION, make_messages


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def redact(text, aliases):
    text = str(text or '')
    # Apply the same credential protection to manual previews and automatic jobs.
    # Handle quoted JSON/config values and complete HTTP authorization schemes.
    value = r'''(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,，;；。"'<>]+)'''
    text = re.sub(
        r'''(?ix)(?<![\w])(?:authorization)["']?\s*[:=：]\s*["']?'''
        r'''(?:(?:bearer|basic)\s+)?[^\s,，;；。"'<>]+["']?''',
        '[凭据已脱敏]', text,
    )
    text = re.sub(
        r'''(?ix)(?<![\w])(?:api[_ -]?key|(?:access|refresh|auth)[_ -]?token|token|password|passwd|pwd|client[_ -]?secret|secret|密码|密钥)["']?\s*[:=：]\s*'''
        + value,
        '[凭据已脱敏]', text,
    )
    text = re.sub(
        r'(?i)\b([a-z][a-z0-9+.-]*://)[^\s/@:]+:[^\s/@]+@',
        r'\1[凭据已脱敏]@', text,
    )
    for name in sorted(aliases, key=len, reverse=True):
        if name:
            text = text.replace(name, aliases[name])
    # Conservative built-in redaction. The preview remains the authority for upload consent.
    for pattern in (r'(?<!\d)1[3-9]\d{9}(?!\d)', r'\b\d{17}[\dXx]\b',
                    r'\b(?:10|127)\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
                    r'\b192\.168\.\d{1,3}\.\d{1,3}\b', r'\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b',
                    r'\bsk-[A-Za-z0-9_-]+', r'(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b',
                    r'(?:/Users/|/home/|[A-Za-z]:\\)[^\s，。；]+', r'\b(?:wxid_|[\w-]+@chatroom)[\w-]*'):
        text = re.sub(pattern, '[已脱敏]', text)
    return text


def build_context(conn, source_id, new_ids, config):
    require_source(conn, source_id)
    if not new_ids or len(new_ids) > config.max_batch_messages or len(set(new_ids)) != len(new_ids):
        raise DeliveryError('invalid_range', '请选择有效消息范围，单批不超过配置数量')
    rows = [dict(r) for r in conn.execute('SELECT id,sender,source_time,content_text,quote_sender,quote_content FROM messages WHERE project_source_id=? AND id IN (%s)' % ','.join('?'*len(new_ids)), (source_id,*new_ids))]
    if {r['id'] for r in rows} != set(new_ids):
        raise DeliveryError('evidence_expired', '消息已过期或不属于当前来源', 409)
    overlap = [dict(r) for r in conn.execute('SELECT id,sender,source_time,content_text,quote_sender,quote_content FROM messages WHERE project_source_id=? AND id<? ORDER BY id DESC LIMIT 20', (source_id,min(new_ids)))]
    total_open = conn.execute("SELECT COUNT(*) FROM work_items WHERE project_source_id=? AND work_status!='resolved' AND review_status!='ignored' AND merged_into IS NULL AND withdrawn_at IS NULL AND evidence_expired=0", (source_id,)).fetchone()[0]
    items = [dict(r) for r in conn.execute("SELECT * FROM work_items WHERE project_source_id=? AND work_status!='resolved' AND review_status!='ignored' AND merged_into IS NULL AND withdrawn_at IS NULL AND evidence_expired=0 ORDER BY id DESC LIMIT 100", (source_id,))]
    evidence = {}
    for item in items:
        evidence[item['id']] = [dict(r) for r in conn.execute('SELECT DISTINCT m.id,m.sender,m.source_time,m.content_text,m.quote_sender,m.quote_content FROM item_evidence e JOIN messages m ON m.id=e.message_id WHERE e.item_id=? ORDER BY m.id DESC LIMIT 10', (item['id'],))]
    names = {r[0] for r in conn.execute('SELECT DISTINCT sender FROM messages WHERE project_source_id=?', (source_id,))}
    all_evidence=[r for group in evidence.values() for r in group]
    names.update(r['quote_sender'] for r in rows+overlap+all_evidence if r['quote_sender'])
    names.update(r['owner'] for r in items if r['owner'])
    aliases = {name:f'person-{index+1}' for index,name in enumerate(sorted(names)) if name}
    def assemble():
        selected = {r['id']:r for r in rows+overlap}
        for item in items:
            selected.update({r['id']:r for r in evidence[item['id']]})
        used_people = set()
        messages = []
        for r in sorted(selected.values(), key=lambda r:(r['source_time'],r['id'])):
            ref = aliases.get(r['sender'])
            if ref: used_people.add(ref)
            quote_ref = aliases.get(r['quote_sender'])
            if quote_ref: used_people.add(quote_ref)
            messages.append({'id':r['id'], 'timestamp':r['source_time'], 'sender_ref':ref,
                             'text':redact(r['content_text'], aliases), 'quote_sender_ref':quote_ref,
                             'quote_text':redact(r['quote_content'], aliases)})
        open_items=[]
        for item in items:
            owner_ref=aliases.get(item['owner'])
            if owner_ref: used_people.add(owner_ref)
            open_items.append({'id':item['id'], 'version':item['version'], 'type':item['type'],
                               'title':redact(item['title'],aliases), 'owner_ref':owner_ref,
                               'work_status':item['work_status'], 'due_text':redact(item['due_text'],aliases),
                               'latest_progress':redact(item['latest_progress'],aliases),
                               'evidence_message_ids':[r['id'] for r in evidence[item['id']]]})
        context={'new_message_ids':new_ids,'persons':{ref:f'成员{ref.split("-")[1]}' for ref in sorted(used_people)},
                 'messages':messages,'open_items':open_items,
                 'coverage':{'new_message_count':len(new_ids),'overlap_count':len(overlap),
                             'open_item_count':total_open,'included_open_item_count':len(items),
                             'partial_context':len(items)<total_open or len(overlap)<initial_overlap}}
        return context
    initial_overlap=len(overlap)
    while True:
        context=assemble()
        # Leave space for the one permitted format correction.
        if len(json.dumps(make_messages(context),ensure_ascii=False))+220 <= config.max_input_chars:
            break
        if items:
            items.pop()
        elif overlap:
            overlap.pop()
        else:
            raise DeliveryError('input_too_large','本批正文超过上下文上限，请缩小批次或提高字符上限')
    persons={ref:name for name,ref in aliases.items() if ref in context['persons']}
    versions={str(item['id']):item['version'] for item in items}
    config_json=config.model_dump()
    digest=hashlib.sha256(encode({'context':context,'persons':persons,'versions':versions,'prompt':PROMPT_VERSION,'config':config_json}).encode()).hexdigest()
    return {'context':context,'persons':persons,'versions':versions,'config':config_json,
            'input_hash':digest,'input_ids':new_ids,'context_ids':[r['id'] for r in context['messages']]}


def next_batch(conn, source_id, after, through, config):
    sql='SELECT id FROM messages WHERE project_source_id=? AND id>?'
    args=[source_id,after]
    if through is not None:
        sql+=' AND id<=?';args.append(through)
    all_ids=[r[0] for r in conn.execute(sql+' ORDER BY id LIMIT ?',(*args,config.max_batch_messages+1))]
    ids=all_ids[:config.max_batch_messages]
    if not ids:
        raise DeliveryError('no_messages','此范围没有待分析消息')
    while True:
        try:
            built=build_context(conn,source_id,ids,config)
            built['has_more']=len(all_ids)>len(ids)
            return built
        except DeliveryError as exc:
            if exc.code!='input_too_large' or len(ids)==1:
                raise
            ids=ids[:max(1,len(ids)//2)]
