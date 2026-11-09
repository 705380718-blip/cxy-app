#!/usr/bin/env python3
"""Isolated CLI evaluation. Fixture mocks exercise plumbing, never real quality."""
from __future__ import annotations
import argparse
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from app.config import Settings
from app.main import create_app
from app.models import DecoderMessage,ProjectCreate,SourceBind,AnalysisPreview,AnalysisEnqueue,EvaluationRequest
from app.ai.settings import AISettingsUpdate
from app.work_items import DeliveryError


def main():
    parser=argparse.ArgumentParser(description='同样本规则/AI 评测；默认只运行本地规则')
    parser.add_argument('--dataset',type=Path,default=Path('tests/fixtures/delivery-evaluation.json'))
    parser.add_argument('--mode',choices=['rules','mock','deepseek'],default='rules')
    parser.add_argument('--output',type=Path,default=Path('output/evaluation'))
    parser.add_argument('--consent-deepseek',action='store_true')
    parser.add_argument('--model',default='deepseek-flash')
    parser.add_argument('--reviews',type=Path,help='人工复核 JSON，含 rule_reviews/ai_reviews；真实模型不自动做语义评分')
    args=parser.parse_args()
    if args.mode=='deepseek' and (not args.consent_deepseek or not os.environ.get('DEEPSEEK_API_KEY')):parser.error('真实模型需显式 --consent-deepseek，并由 DEEPSEEK_API_KEY 提供密钥；勿放进命令参数')
    try:
        dataset=json.loads(args.dataset.read_text());origin=dataset['data_origin']
        if origin not in ('constructed','deidentified_work'):parser.error('dataset data_origin 必须标明 constructed 或 deidentified_work')
        if args.mode=='mock' and origin!='constructed':parser.error('mock 仅支持构造样例')
        with tempfile.TemporaryDirectory(prefix='delivery-evaluation-') as temp:
            root=Path(temp);source_name='评测隔离来源'
            app=create_app(Settings(host='127.0.0.1',port=8794,database_path=root/'data.db',wechat_app_path=root/'absent',wechat_data_root=root/'empty',decoder_command=(),decoder_baseline_epoch=0,max_verified_wechat_version='4.1.12',allow_unverified_decoder=False,poll_interval_seconds=2,initial_groups=(source_name,),initial_self_names=()),start_analysis_worker=False)
            project=app.state.delivery.create_project(ProjectCreate(name='评测隔离项目'));source=app.state.delivery.bind_source(project['id'],SourceBind(source_kind='import',source_key=source_name,display_name=source_name))
            mapping={}
            for m in dataset['messages']:
                if m['id'] in mapping:parser.error('消息 ID 重复')
                app.state.service.ingest_many([DecoderMessage(source_id='evaluation-'+m['id'],chat_name=source_name,sender=m['sender'],content=m['content'],source_time=datetime.fromisoformat(m['timestamp']),source_kind='import')],project_source_id=source['id'])
                with app.state.service.database.connection() as conn:mapping[m['id']]=conn.execute('SELECT MAX(id) FROM messages').fetchone()[0]
            labels=[{**l,'evidence_message_ids':[mapping[mid] for mid in l['evidence_message_ids']]} for l in dataset['labels']]
            if args.mode!='rules':
                app.state.ai_store.save(AISettingsUpdate(enabled=True,model='mock-fixture-evaluation' if args.mode=='mock' else args.model,api_key='fixture-placeholder' if args.mode=='mock' else os.environ['DEEPSEEK_API_KEY']))
                if args.mode=='mock':
                    def handler(request):
                        # Deliberately returns fixture labels; this measures no inference ability.
                        context=json.loads(json.loads(request.content)['messages'][1]['content'])
                        texts={m['id']:m['text'] for m in context['messages']}
                        result={'schema_version':1,'items':[{'candidate_key':l['id'],'target_item_id':None,'type':l['type'],'title':l['title'],'task_basis':{'kind':'commitment','message_id':l['evidence_message_ids'][0],'quote':texts[l['evidence_message_ids'][0]]} if l['type']=='task' else None,'owner_ref':None,'due_text':None,'due_at':None,'suggested_status':'open','latest_progress':None,'evidence_message_ids':l['evidence_message_ids'],'field_evidence':{},'needs_confirmation':[]} for l in labels]}
                        return httpx.Response(200,json={'model':'mock-fixture-evaluation','choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]})
                    app.state.ai_client.transport=httpx.MockTransport(handler)
                while True:
                    preview=app.state.ai_jobs.preview(AnalysisPreview(project_source_id=source['id']))
                    if not preview.get('preview_token'):break
                    app.state.ai_jobs.enqueue(AnalysisEnqueue(preview_token=preview['preview_token'],consent=True))
                    asyncio.run(app.state.ai_worker.run_once())
                    if len(preview['context']['new_message_ids'])==0:break
                    with app.state.service.database.connection() as conn:
                        latest=conn.execute('SELECT status FROM ai_jobs ORDER BY id DESC LIMIT 1').fetchone()[0]
                    if latest!='succeeded':break
                    # Manual enqueue does not advance the automation cursor; use explicit boundary.
                    if max(preview['context']['new_message_ids'])>=max(mapping.values()):break
                    parser.error('CLI 样本超过单批上限，请按批拆分；大样本通过页面评测')
            inputs=app.state.evaluations.inputs(project['id'])
            reviews=json.loads(args.reviews.read_text()) if args.reviews else {'rule_reviews':[],'ai_reviews':[]}
            if origin=='constructed' and args.mode in ('rules','mock') and not args.reviews:
                for key,predkey in [('rule_reviews','rule_predictions'),('ai_reviews','ai_predictions')]:
                    matched=set()
                    for p in inputs[predkey]:
                        match=next((l for l in labels if l['id'] not in matched and l['type']==p['type'] and set(l['evidence_message_ids'])==set(p['evidence_message_ids'])),None)
                        if match:matched.add(match['id'])
                        reviews[key].append({'prediction_id':p['id'],'label_id':match['id'] if match else None,'field_evidence_verified':None})
            result=app.state.evaluations.create(EvaluationRequest(project_id=project['id'],dataset_label=dataset['dataset_label'],data_origin=origin,mode='simulated' if origin=='constructed' else 'replay',scope_message_ids=list(mapping.values()),labels=labels,reviewer_label='构造验收映射' if origin=='constructed' and args.mode!='deepseek' else 'CLI人工复核',familiarity_note='构造样例按固定依据与类型映射；mock 直接返回标签，仅验证统计链路。' if args.mode!='deepseek' else '真实模型结果须另行人工复核，未复核指标保持空值。',attested=True,**reviews))
            args.output.mkdir(parents=True,exist_ok=True)
            (args.output/'evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
            (args.output/'evaluation.csv').write_text(app.state.evaluations.export(result['id']),encoding='utf-8')
            print(json.dumps({'mode':args.mode,'data_origin':origin,'sample_count':len(mapping),'quality_goal_eligible':False,'output':str(args.output)},ensure_ascii=False))
    except (ValueError,KeyError,OSError,DeliveryError) as exc:
        # Do not echo dataset/provider content or credentials in error output.
        parser.exit(1,'[错误] 样本/复核文件格式不合法或文件操作失败，请检查输入。\n')

if __name__=='__main__':main()
