from __future__ import annotations

import json
import sqlite3

from .models import ProjectCreate, SourceBind, WorkItemCreate, WorkItemUpdate, ProposalApply
from .service import iso, now_utc


class DeliveryError(Exception):
    def __init__(self, code, detail, status=422):
        self.code, self.detail, self.status = code, detail, status
        super().__init__(detail)


def require_source(conn, source_id, kind=None):
    row = conn.execute('SELECT s.* FROM project_sources s JOIN projects p ON p.id=s.project_id WHERE s.id=? AND p.enabled=1', (source_id,)).fetchone()
    if row is None:
        raise DeliveryError('source_not_found', '消息来源不存在或项目已停用', 404)
    if kind and row['source_kind'] != kind:
        raise DeliveryError('source_kind_mismatch', '请选择文本导入来源')
    groups = json.loads(conn.execute('SELECT groups_json FROM settings WHERE id=1').fetchone()[0])
    if row['source_key'] not in groups:
        raise DeliveryError('group_not_allowed', '来源群名未在白名单中，请先在提取规则中添加')
    return row


class WorkItemService:
    def __init__(self, database):
        self.database = database

    def projects(self):
        with self.database.connection() as conn:
            projects = [dict(r) for r in conn.execute('SELECT * FROM projects ORDER BY id')]
            for p in projects:
                p['sources'] = [dict(r) for r in conn.execute('SELECT s.*, COUNT(m.id) AS message_count, MIN(m.source_time) AS period_start, MAX(m.source_time) AS period_end FROM project_sources s LEFT JOIN messages m ON m.project_source_id=s.id WHERE s.project_id=? GROUP BY s.id ORDER BY s.id', (p['id'],))]
        return {'items': projects}

    def create_project(self, data: ProjectCreate):
        with self.database.connection() as conn:
            try:
                cur = conn.execute('INSERT INTO projects(name,created_at) VALUES (?,?)', (data.name, iso(now_utc())))
            except sqlite3.IntegrityError as exc:
                raise DeliveryError('project_exists', '项目名称已存在', 409) from exc
            return dict(conn.execute('SELECT * FROM projects WHERE id=?', (cur.lastrowid,)).fetchone())

    def bind_source(self, project_id, data: SourceBind):
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            if not conn.execute('SELECT id FROM projects WHERE id=? AND enabled=1', (project_id,)).fetchone():
                raise DeliveryError('project_not_found', '项目不存在', 404)
            groups = json.loads(conn.execute('SELECT groups_json FROM settings WHERE id=1').fetchone()[0])
            if data.source_key not in groups:
                raise DeliveryError('group_not_allowed', '请先在提取规则白名单中添加精确群名')
            old = conn.execute('SELECT * FROM project_sources WHERE source_kind=? AND source_key=?', (data.source_kind, data.source_key)).fetchone()
            if old and old['project_id'] != project_id:
                raise DeliveryError('source_bound', '该来源已绑定其他项目', 409)
            if old:
                conn.execute('UPDATE project_sources SET display_name=? WHERE id=?', (data.display_name, old['id']))
                return dict(conn.execute('SELECT * FROM project_sources WHERE id=?', (old['id'],)).fetchone())
            cur = conn.execute('INSERT INTO project_sources(project_id,source_kind,source_key,display_name) VALUES (?,?,?,?)', (project_id, data.source_kind, data.source_key, data.display_name))
            # Binding applies to future listener input only. History is never silently assigned.
            return dict(conn.execute('SELECT * FROM project_sources WHERE id=?', (cur.lastrowid,)).fetchone())

    def create_item(self, data: WorkItemCreate):
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            require_source(conn, data.project_source_id)
            ids = set(data.evidence_message_ids)
            found = {r[0] for r in conn.execute('SELECT id FROM messages WHERE project_source_id=? AND id IN (%s)' % ','.join('?' * len(ids)), (data.project_source_id, *ids))}
            if found != ids:
                raise DeliveryError('evidence_out_of_scope', '依据消息必须全部属于当前项目来源')
            now = iso(now_utc())
            cur = conn.execute('INSERT INTO work_items(project_source_id,type,title,created_at,updated_at) VALUES (?,?,?,?,?)', (data.project_source_id, data.type, data.title, now, now))
            for mid in ids:
                conn.execute('INSERT INTO item_evidence(item_id,message_id,field) VALUES (?,?,?)', (cur.lastrowid, mid, 'title'))
            return dict(conn.execute('SELECT * FROM work_items WHERE id=?', (cur.lastrowid,)).fetchone())

    def list_items(self, project_id=None, review_status=None, work_status=None, page=1, page_size=20, withdrawn=False):
        filters, args = ['w.merged_into IS NULL', 'w.withdrawn_at IS NOT NULL' if withdrawn else 'w.withdrawn_at IS NULL'], []
        for column, value in [('s.project_id', project_id), ('w.review_status', review_status), ('w.work_status', work_status)]:
            if value is not None:
                filters.append(f'{column}=?')
                args.append(value)
        sql = ' FROM work_items w JOIN project_sources s ON s.id=w.project_source_id WHERE ' + ' AND '.join(filters)
        with self.database.connection() as conn:
            total = conn.execute('SELECT COUNT(*)' + sql, args).fetchone()[0]
            page = min(page,max(1,(total+page_size-1)//page_size))
            rows = conn.execute('SELECT w.*,s.project_id,s.display_name' + sql + ' ORDER BY w.id DESC LIMIT ? OFFSET ?', (*args, page_size, (page-1)*page_size))
            return {'items': [dict(r) for r in rows], 'total': total, 'page': page, 'page_size': page_size}

    def evidence(self, item_id):
        with self.database.connection() as conn:
            if not conn.execute('SELECT id FROM work_items WHERE id=?', (item_id,)).fetchone():
                raise DeliveryError('item_not_found', '事项不存在', 404)
            rows = conn.execute('SELECT e.field,m.id,m.chat_name,m.sender,m.source_time,m.source_kind,m.content_text,m.quote_sender,m.quote_content FROM item_evidence e JOIN messages m ON m.id=e.message_id WHERE e.item_id=? ORDER BY m.source_time,m.id', (item_id,))
            return {'items': [dict(r) for r in rows]}

    def update_item(self, item_id, data: WorkItemUpdate):
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM work_items WHERE id=?', (item_id,)).fetchone()
            if not row:
                raise DeliveryError('item_not_found', '事项不存在', 404)
            if row['version'] != data.expected_version:
                raise DeliveryError('version_conflict', '事项已更新，请刷新后重试', 409)
            if row['evidence_expired'] or row['merged_into'] or row['withdrawn_at']:
                raise DeliveryError('item_inactive', '事项已撤回、合并或依据已过期', 409)
            fields = data.model_dump(exclude_unset=True, mode='json')
            fields.pop('expected_version')
            if any(fields.get(k, row[k]) is None for k in ('title','review_status','work_status')):
                raise DeliveryError('required_field', '标题及状态不能为空')
            if not fields:
                return dict(row)
            assignments = ','.join(f'{key}=?' for key in fields)
            conn.execute(f'UPDATE work_items SET {assignments},human_edited=1,version=version+1,updated_at=? WHERE id=?', (*fields.values(), iso(now_utc()), item_id))
            conn.execute('INSERT INTO audit_log(action,detail_json,created_at) VALUES (?,?,?)', ('delivery_item_edit', json.dumps({'item_id':item_id,'version':row['version']+1,'fields':list(fields)}), iso(now_utc())))
            return dict(conn.execute('SELECT * FROM work_items WHERE id=?', (item_id,)).fetchone())

    def set_withdrawn(self, item_id, expected_version, withdrawn):
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT * FROM work_items WHERE id=?', (item_id,)).fetchone()
            if not row:
                raise DeliveryError('item_not_found','事项不存在',404)
            if bool(row['withdrawn_at']) == withdrawn:
                return dict(row)
            if row['version'] != expected_version:
                raise DeliveryError('version_conflict','事项已更新，请刷新后重试',409)
            if row['merged_into'] or (not withdrawn and row['evidence_expired']):
                raise DeliveryError('item_inactive','事项已撤回、合并或依据已过期，无法恢复',409)
            if withdrawn and row['review_status'] != 'confirmed' and not row['auto_generated']:
                raise DeliveryError('item_unconfirmed','仅已确认事项可撤回',409)
            now = iso(now_utc())
            conn.execute('UPDATE work_items SET withdrawn_at=?,human_edited=1,version=version+1,updated_at=? WHERE id=?', (now if withdrawn else None,now,item_id))
            conn.execute('INSERT INTO audit_log(action,detail_json,created_at) VALUES (?,?,?)', ('delivery_item_withdraw' if withdrawn else 'delivery_item_restore',json.dumps({'item_id':item_id,'version':row['version']+1}),now))
            return dict(conn.execute('SELECT * FROM work_items WHERE id=?',(item_id,)).fetchone())

    def proposals(self, project_id=None, page=1, page_size=100, item_type=None):
        with self.database.connection() as conn:
            joined="FROM item_proposals p JOIN ai_jobs j ON j.id=p.job_id JOIN project_sources s ON s.id=j.project_source_id WHERE p.status='pending' AND (p.target_item_id IS NULL OR EXISTS (SELECT 1 FROM work_items w WHERE w.id=p.target_item_id AND w.withdrawn_at IS NULL))"
            args=[]
            if project_id is not None:joined+=' AND s.project_id=?';args.append(project_id)
            if item_type is not None:joined+=" AND json_extract(p.proposed_fields_json,'$.type')=?";args.append(item_type)
            total=conn.execute('SELECT COUNT(*) '+joined,args).fetchone()[0]
            pages=max(1,(total+page_size-1)//page_size);page=min(page,pages)
            rows=[dict(r) for r in conn.execute('SELECT p.*,j.project_source_id,s.display_name,s.project_id '+joined+' ORDER BY p.id DESC LIMIT ? OFFSET ?',[*args,page_size,(page-1)*page_size])]
            for row in rows:
                row['fields']=json.loads(row.pop('proposed_fields_json'))
                row['evidence_message_ids']=json.loads(row.pop('evidence_ids'))
            return {'items':rows,'total':total,'page':page,'pages':pages,'page_size':page_size}

    def proposal_evidence(self, proposal_id):
        with self.database.connection() as conn:
            row=conn.execute('SELECT evidence_ids FROM item_proposals WHERE id=?',(proposal_id,)).fetchone()
            if not row:raise DeliveryError('proposal_not_found','建议不存在',404)
            ids=json.loads(row[0])
            rows=conn.execute('SELECT id,sender,source_time,content_text,quote_sender,quote_content,source_kind FROM messages WHERE id IN (%s) ORDER BY source_time,id' % ','.join('?'*len(ids)),ids) if ids else []
            return {'items':[dict(r) for r in rows]}

    def apply_proposal(self, proposal_id, data, project_id=None):
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            return self._apply_proposal(conn,proposal_id,data,project_id)

    def _apply_proposal(self,conn,proposal_id,data,project_id=None,automatic=False):
        p=conn.execute('SELECT p.*,j.project_source_id FROM item_proposals p JOIN ai_jobs j ON j.id=p.job_id WHERE p.id=?',(proposal_id,)).fetchone()
        if not p:raise DeliveryError('proposal_not_found','建议不存在',404)
        self._proposal_scope(conn,p['project_source_id'],project_id)
        if p['status']=='applied':
            applied=conn.execute('SELECT * FROM work_items WHERE id=?',(p['applied_item_id'],)).fetchone()
            if applied['withdrawn_at']:raise DeliveryError('item_withdrawn','事项已撤回，请从已撤回列表恢复',409)
            return dict(applied)
        if p['status']!='pending':raise DeliveryError('proposal_inactive','建议已忽略',409)
        require_source(conn,p['project_source_id'])
        ids=json.loads(p['evidence_ids'])
        found={r[0] for r in conn.execute('SELECT id FROM messages WHERE project_source_id=? AND id IN (%s)' % ','.join('?'*len(ids)),(p['project_source_id'],*ids))} if ids else set()
        if not ids or found!=set(ids):raise DeliveryError('evidence_expired','建议依据已过期',409)
        target_id=p['target_item_id'] or data.target_item_id
        if p['target_item_id'] and data.target_item_id not in (None,p['target_item_id']):
            raise DeliveryError('target_mismatch','此进展建议已绑定指定事项')
        fields=json.loads(p['proposed_fields_json'])
        now=iso(now_utc())
        # Automatic results stay unconfirmed; human edits are protected from future automation.
        changes={'type':fields['type'],'title':fields['title'],'work_status':fields['work_status'],'review_status':'pending' if automatic else 'confirmed','human_edited':0 if automatic else 1}
        for field in ('owner','due_text','due_at','latest_progress'):
            if fields.get(field) is not None:changes[field]=fields[field]
        if fields.get('due_text') is not None:
            # An accepted ambiguous deadline must clear an older precise date.
            changes['due_at']=fields.get('due_at')
        if automatic and not target_id:
            for existing in conn.execute('SELECT * FROM work_items WHERE project_source_id=? AND type=? AND title=? AND merged_into IS NULL AND withdrawn_at IS NULL AND evidence_expired=0',(p['project_source_id'],fields['type'],fields['title'])):
                previous={r[0] for r in conn.execute("SELECT message_id FROM item_evidence WHERE item_id=? AND field='title'",(existing['id'],))}
                if previous==set(ids):
                    conn.execute("UPDATE item_proposals SET status='applied',applied_item_id=? WHERE id=?",(existing['id'],proposal_id))
                    return dict(existing)
        if target_id:
            target=conn.execute('SELECT * FROM work_items WHERE id=?',(target_id,)).fetchone()
            if not target or target['project_source_id']!=p['project_source_id']:
                raise DeliveryError('target_out_of_scope','只能关联同一项目来源事项')
            if target['merged_into'] or target['evidence_expired'] or target['withdrawn_at']:
                raise DeliveryError('item_inactive','事项已撤回、合并或依据已过期',409)
            expected=p['target_version'] if p['target_item_id'] else data.expected_version
            if data.expected_version!=expected or target['version']!=expected:
                raise DeliveryError('version_conflict','事项在分析后已更新，请保留人工修改，重新分析或忽略此建议',409)
            if automatic and (not target['auto_generated'] or target['human_edited'] or target['review_status']!='pending'):
                raise DeliveryError('human_protected','保留人工记录，请查看进展建议',409)
            if target['work_status']=='resolved':raise DeliveryError('item_closed','事项已人工关闭，请人工修改状态后重新分析',409)
            assignments=','.join(f'{key}=?' for key in changes)
            conn.execute(f'UPDATE work_items SET {assignments},version=version+1,updated_at=? WHERE id=?',(*changes.values(),now,target_id))
            item_id=target_id
        else:
            if data.expected_version is not None:raise DeliveryError('version_invalid','新事项无需提供旧版本')
            changes['auto_generated']=int(automatic)
            columns=','.join(changes)
            values=','.join('?'*len(changes))
            cur=conn.execute(f'INSERT INTO work_items(project_source_id,{columns},created_at,updated_at) VALUES(?,{values},?,?)',(p['project_source_id'],*changes.values(),now,now))
            item_id=cur.lastrowid
        evidence={'title':ids,**fields.get('field_evidence',{})}
        for field,message_ids in evidence.items():
            for mid in message_ids:
                conn.execute('INSERT OR IGNORE INTO item_evidence(item_id,message_id,field,job_id) VALUES(?,?,?,?)',(item_id,mid,field,p['job_id']))
        conn.execute("UPDATE item_proposals SET status='applied',applied_item_id=? WHERE id=?",(item_id,proposal_id))
        conn.execute('INSERT INTO audit_log(action,detail_json,created_at) VALUES(?,?,?)',('delivery_proposal_auto_publish' if automatic else 'delivery_proposal_apply',json.dumps({'proposal_id':proposal_id,'item_id':item_id,'fields':list(changes)}),now))
        return dict(conn.execute('SELECT * FROM work_items WHERE id=?',(item_id,)).fetchone())

    def dismiss_proposal(self, proposal_id, project_id=None):
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            row=conn.execute('SELECT p.status,j.project_source_id FROM item_proposals p JOIN ai_jobs j ON j.id=p.job_id WHERE p.id=?',(proposal_id,)).fetchone()
            if not row:raise DeliveryError('proposal_not_found','建议不存在',404)
            self._proposal_scope(conn,row['project_source_id'],project_id)
            if row[0]=='applied':raise DeliveryError('proposal_applied','建议已采纳，请在事项中调整',409)
            conn.execute("UPDATE item_proposals SET status='dismissed' WHERE id=?",(proposal_id,))
            if row[0]=='pending':
                conn.execute('INSERT INTO audit_log(action,detail_json,created_at) VALUES(?,?,?)',('delivery_proposal_dismiss',json.dumps({'proposal_id':proposal_id}),iso(now_utc())))
            return {'status':'dismissed'}

    @staticmethod
    def _proposal_scope(conn, source_id, project_id):
        if project_id is not None and not conn.execute('SELECT id FROM project_sources WHERE id=? AND project_id=?',(source_id,project_id)).fetchone():
            raise DeliveryError('proposal_out_of_scope','建议不属于当前项目',409)

    def batch_proposals(self, data):
        # Each suggestion commits independently; normal evidence/version checks and
        # idempotence still apply when retrying after a partial or interrupted batch.
        results=[]
        for item in data.items:
            try:
                if data.action == 'apply':
                    applied=self.apply_proposal(item.id,ProposalApply(expected_version=item.expected_version),data.project_id)
                    results.append({'id':item.id,'ok':True,'item_id':applied['id']})
                else:
                    self.dismiss_proposal(item.id,data.project_id)
                    results.append({'id':item.id,'ok':True})
            except DeliveryError as exc:
                results.append({'id':item.id,'ok':False,'code':exc.code,'detail':exc.detail})
        succeeded=sum(result['ok'] for result in results)
        return {'action':data.action,'results':results,'succeeded':succeeded,'failed':len(results)-succeeded}

    def merge_items(self, item_id, data):
        with self.database.connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            a=conn.execute('SELECT * FROM work_items WHERE id=?',(item_id,)).fetchone()
            b=conn.execute('SELECT * FROM work_items WHERE id=?',(data.target_item_id,)).fetchone()
            if not a or not b:raise DeliveryError('item_not_found','事项不存在',404)
            if item_id==data.target_item_id or a['project_source_id']!=b['project_source_id']:
                raise DeliveryError('merge_scope','只能合并同来源的两个不同事项')
            if a['merged_into'] or b['merged_into'] or a['evidence_expired'] or b['evidence_expired'] or a['withdrawn_at'] or b['withdrawn_at']:
                raise DeliveryError('item_inactive','事项已撤回、合并或依据已过期',409)
            if a['version']!=data.expected_version or b['version']!=data.target_version:
                raise DeliveryError('version_conflict','事项已更新，请刷新后重试',409)
            conn.execute('INSERT OR IGNORE INTO item_evidence(item_id,message_id,field,job_id) SELECT ?,message_id,field,job_id FROM item_evidence WHERE item_id=?',(b['id'],a['id']))
            now=iso(now_utc())
            conn.execute('UPDATE work_items SET merged_into=?,human_edited=1,version=version+1,updated_at=? WHERE id=?',(b['id'],now,a['id']))
            conn.execute('UPDATE work_items SET human_edited=1,version=version+1,updated_at=? WHERE id=?',(now,b['id']))
            conn.execute('INSERT INTO audit_log(action,detail_json,created_at) VALUES(?,?,?)',('delivery_item_merge',json.dumps({'from_item':a['id'],'to_item':b['id']}),now))
            return dict(conn.execute('SELECT * FROM work_items WHERE id=?',(b['id'],)).fetchone())
