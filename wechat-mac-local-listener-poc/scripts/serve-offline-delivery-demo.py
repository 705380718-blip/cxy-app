#!/usr/bin/env python3
"""Temporary, constructed UI fixture; no cloud request or real credentials."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

import httpx
import uvicorn

from app.ai.settings import AISettingsUpdate
from app.config import Settings
from app.main import create_app
from app.models import DecoderMessage, ProjectCreate, SourceBind


def main():
    parser=argparse.ArgumentParser(description='构造样例 + 模拟模型接口，仅验证页面操作')
    parser.add_argument('--port',type=int,default=int(os.getenv('WML_OFFLINE_DEMO_PORT','8793')))
    parser.add_argument("--candidate-count",type=int,choices=range(1,21),default=1,help="每批构造建议数，1–20，仅用于批量操作验收")
    args=parser.parse_args()
    if args.port in (5173,8000,8791,8792) or not 1024<=args.port<=65535:
        parser.error('请选择 1024–65535 的独立端口；常用开发/正常应用端口被保留')
    with tempfile.TemporaryDirectory(prefix='delivery-offline-demo-') as temp:
        root=Path(temp)
        app=create_app(Settings(host='127.0.0.1',port=args.port,database_path=root/'demo.db',wechat_app_path=root/'absent-WeChat.app',wechat_data_root=root/'empty-wechat',decoder_command=(),decoder_baseline_epoch=0,max_verified_wechat_version='4.1.12',allow_unverified_decoder=False,poll_interval_seconds=2,initial_groups=('构造样例-模拟接口',),initial_self_names=('演示助手',)))
        project=app.state.delivery.create_project(ProjectCreate(name='构造样例-离线接口模拟'))
        source=app.state.delivery.bind_source(project['id'],SourceBind(source_kind='import',source_key='构造样例-模拟接口',display_name='构造样例-模拟接口'))
        for i,(sender,text) in enumerate([('客户甲','验收材料缺拓扑，请补充。'),('同事甲','我负责，明天 12:00 提交。'),('同事甲','拓扑已上传，待客户复核。')]):
            app.state.service.ingest_many([DecoderMessage(source_id=f'offline-ui-{i}',chat_name=source['source_key'],sender=sender,content=text,source_time=datetime(2026,10,10,1,i,tzinfo=timezone.utc),source_kind='import')],project_source_id=source['id'])
        app.state.ai_store.save(AISettingsUpdate(enabled=True,model='mock-delivery-fixture',api_key='offline-placeholder-never-sent'))
        def handler(request):
            if request.url.path.endswith('/models'):
                return httpx.Response(200,json={'data':[{'id':'mock-delivery-fixture'}]})
            context=json.loads(json.loads(request.content)['messages'][1]['content'])
            messages=context['messages'];ids=[m['id'] for m in messages]
            basis=next(m for m in messages if m['id']==context['new_message_ids'][0])
            owner=messages[1]['sender_ref'];target=context['open_items'][0]['id'] if context['open_items'] else None
            result={'schema_version':1,'items':[{'candidate_key':'mock-1','target_item_id':target,'type':'task','title':'构造样例：补充验收拓扑','task_basis':{'kind':'request','message_id':basis['id'],'quote':basis['text']},'owner_ref':owner,'due_text':'明天 12:00','due_at':None,'suggested_status':'waiting_confirmation','latest_progress':'构造样例：已上传，等待客户复核','evidence_message_ids':ids,'field_evidence':{'owner':[ids[1]],'deadline':[ids[1]],'progress':[ids[-1]]},'needs_confirmation':[]}]}
            fixture=result['items'][0]
            result['items']=[{**fixture,'candidate_key':f'mock-{i+1}','title':fixture['title']+(f'（{i+1}）' if args.candidate_count>1 else '')} for i in range(args.candidate_count)]
            return httpx.Response(200,json={'id':'offline-demo','model':'mock-delivery-fixture','usage':{'total_tokens':123},'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]})
        app.state.ai_client.transport=httpx.MockTransport(handler)
        print(f'[离线 UI 测试] http://127.0.0.1:{args.port}/ · 构造样例/模拟接口 · 不调用真实模型',flush=True)
        uvicorn.run(app,host='127.0.0.1',port=args.port,log_level='warning')


if __name__=='__main__':main()
