import json

import httpx
import pytest

from app.ai.schemas import ItemCandidate
from app.ai.settings import AISettingsUpdate
from app.ai.task_filter import actionable_quote, supported_task
from test_delivery import bind, imported
from test_ai_workflow import queued, run


@pytest.mark.parametrize('text,expected',[
    ('版本是不是最新？',False),
    ('明天是否提交新版本？',False),
    ('请同步验收安排给大家。',True),
    ('使用哪个数据库，是否同一个实例？',False),
    ('这是一个 MySQL，后端 JAVA 服务。',False),
    ('上半年业绩不好，报表不好看。',False),
    ('材料已经上传，等客户确认。',False),
    ('之前已经整理模板了。',False),
    ('不用再补充资料。',False),
    ('不需要上传拓扑。',False),
    ('请问怎么修改版本？',False),
    ('我看看，等负责人确认再说。',False),
    ('请补充拓扑，已经补充好了。',False),
    ('请核对数据库实例，明天反馈。',True),
    ('我来汇总模板并加入原型。',True),
    ('请确认版本是否符合要求。',True),
    ('能否帮忙核对实例并反馈？',True),
    ('请复核已经上传的拓扑。',True),
    ('我负责，明天 12:00 提交拓扑。',True),
])
def test_questions_facts_completion_and_real_actions(text,expected):
    assert actionable_quote(text,text) == expected


def test_no_invented_or_cropped_action_evidence():
    item=ItemCandidate(candidate_key='x',type='task',title='上传拓扑',evidence_message_ids=[1],task_basis={'kind':'request','message_id':1,'quote':'上传拓扑'})
    assert not supported_task(item,{1:{'text':'不用上传拓扑。'}})
    assert not supported_task(item,{1:{'text':'上传拓扑了吗？'}})
    assert not supported_task(item,{1:{'text':'没有这段原文'}})
    assert not supported_task(item,{2:{'text':'请上传拓扑'}})
    item.task_basis=None
    assert not supported_task(item,{1:{'text':'请上传拓扑'}})
    item.target_item_id=2
    assert supported_task(item,{1:{'text':'已上传，等待结果'}})


def test_worker_filters_only_unsupported_new_tasks_without_retrying(client):
    _,source=bind(client)
    ids=imported(client,source,'[2026-10-10 09:00:00] 同事甲: 版本是不是最新？\n[2026-10-10 09:01:00] 同事乙: 请核对拓扑并反馈。\n[2026-10-10 09:02:00] 客户甲: 接口无法登录。')
    client.app.state.ai_store.save(AISettingsUpdate(enabled=True,api_key='constructed-key'))
    job,_=queued(client,source)
    def handler(request):
        messages=json.loads(json.loads(request.content)['messages'][1]['content'])['messages']
        candidates=[]
        for i,kind in enumerate(['task','task','issue']):
            candidates.append({'candidate_key':str(i),'type':kind,'title':['确认版本','核对拓扑','无法登录'][i],'evidence_message_ids':[ids[i]],'task_basis':{'kind':'request','message_id':ids[i],'quote':messages[i]['text']} if kind=='task' else None})
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'schema_version':1,'items':candidates})}}]})
    assert run(client,handler)
    proposals=client.get('/api/item-proposals').json()['items']
    assert {p['fields']['title'] for p in proposals} == {'核对拓扑','无法登录'}
    saved=client.get(f"/api/ai/jobs/{job['id']}").json()
    assert saved['status'] == 'succeeded' and saved['attempts'] == 1 and saved['filtered_task_count'] == 1
