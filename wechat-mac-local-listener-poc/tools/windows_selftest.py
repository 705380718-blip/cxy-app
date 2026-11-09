"""Offline synthetic end-to-end test. Never reads WeChat, production DB or API keys."""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def run_selftest(directory: Path):
    import httpx
    import zstandard
    from Crypto.Cipher import AES
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.local_session import LocalSession
    from app.main import create_app
    from app.ai.settings import AISettingsUpdate
    from app.platforms.windows_security import apply_current_user_acl,protect_current_user,unprotect_current_user
    checks=[]
    native=os.name=='nt'
    if not native:directory=directory.resolve()
    protect=apply_current_user_acl if native else lambda p:p.chmod(0o700 if p.is_dir() else 0o600)
    directory.mkdir(parents=True,exist_ok=True);protect(directory)
    if native:
        blob=protect_current_user(b'local-synthetic-fixture')
        assert blob != b'local-synthetic-fixture' and unprotect_current_user(blob)==b'local-synthetic-fixture'
        checks.append('native-dpapi-roundtrip-and-private-acl')
    assert zstandard.ZstdDecompressor().decompress(zstandard.ZstdCompressor().compress(b'fixture'))==b'fixture'
    key=bytes(range(32));iv=bytes(16);plain=bytes(32)
    encrypted=AES.new(key,AES.MODE_CBC,iv).encrypt(plain)
    assert AES.new(key,AES.MODE_CBC,iv).decrypt(encrypted)==plain
    checks.append('native-extension-import-and-roundtrip')
    settings=Settings(host='127.0.0.1',port=8794,database_path=directory/'fixture.db',wechat_app_path=directory/'missing-wechat',wechat_data_root=directory/'missing-data',decoder_command=(),decoder_baseline_epoch=0,max_verified_wechat_version='',allow_unverified_decoder=False,poll_interval_seconds=1,initial_groups=(),initial_self_names=('构造助手',),runtime_platform='windows' if native else 'macos',windows_profiles_path=ROOT/'config/windows-decoder-profiles.json',windows_key_store_path=directory/'keys.dpapi',windows_snapshot_root=directory/'snapshots')
    session=LocalSession(directory/'private/session',8794,acl=protect)
    token=re.search(r'name="token" value="([^"]+)"',session.bootstrap_path.read_text()).group(1)
    app=create_app(settings,start_analysis_worker=False,local_session=session)
    today=datetime.now(timezone(timedelta(hours=8)))
    with TestClient(app,base_url='http://127.0.0.1:8794') as c:
        assert c.get('/api/projects').status_code==401
        login=c.post('/api/session/exchange',data={'token':token},headers={'origin':'null'},follow_redirects=False)
        assert login.status_code==303 and 'HttpOnly' in login.headers['set-cookie']
        assert c.post('/api/session/exchange',data={'token':token},headers={'origin':'null'}).status_code==403
        assert c.post('/api/projects',json={'name':'bad'},headers={'origin':'https://example.invalid'}).status_code==403
        checks.append('cookie-access-control-and-origin-protection')
        setup=c.put('/api/workflow/setup',json={'project_name':'离线自检','groups':['构造群'],'self_names':['构造助手'],'source_kind':'import'})
        assert setup.status_code==200,setup.text
        project=setup.json()['project'];source=setup.json()['sources'][0]
        app.state.ai_store.save(AISettingsUpdate(enabled=True,api_key='synthetic-selftest-key'))
        assert 'synthetic-selftest-key' not in c.get('/api/ai/settings').text
        assert c.put('/api/workflow/automation',json={'project_id':project['id'],'enabled':True,'consent':True}).status_code==200
        message=f'[{today.isoformat()}] 构造成员: 我负责明天提交接口说明。'
        p=c.post('/api/imports/preview',json={'project_source_id':source['id'],'format':'txt','content':message}).json()
        assert c.post(f"/api/imports/{p['id']}/commit",json={}).json()['inserted']==1
        assert c.post(f"/api/imports/{p['id']}/commit",json={}).json()['inserted']==0
        checks.append('workflow-import-and-idempotency')
        calls=[]
        def model(request):
            context=json.loads(json.loads(request.content)['messages'][1]['content'])
            mid=context['new_message_ids'][0]
            m=next(m for m in context['messages'] if m['id']==mid)
            result={'schema_version':1,'items':[{'candidate_key':'fixture-1','target_item_id':None,'type':'task','title':'提交接口说明','task_basis':{'kind':'commitment','message_id':mid,'quote':m['text']},'owner_ref':m['sender_ref'],'due_text':'明天','due_at':None,'suggested_status':'open','latest_progress':'已承诺提交','evidence_message_ids':[mid],'field_evidence':{'owner':[mid],'deadline':[mid],'progress':[mid]},'needs_confirmation':[]}]}
            calls.append(1)
            return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(result)}}]})
        app.state.ai_client.transport=httpx.MockTransport(model)
        app.state.ai_jobs.enqueue_automatic()
        assert asyncio.run(app.state.ai_worker.run_once())
        assert calls==[1]
        items=c.get('/api/work-items').json()['items']
        assert len(items)==1 and items[0]['auto_generated']==1
        assert c.get('/api/item-proposals').json()['total']==0
        app.state.ai_jobs.enqueue_automatic()
        assert not asyncio.run(app.state.ai_worker.run_once())
        checks.append('automatic-analysis-to-results-with-mocked-model')
        item=items[0]
        removed=c.request('DELETE',f"/api/work-items/{item['id']}",json={'expected_version':item['version']})
        assert removed.status_code==200 and c.get('/api/work-items').json()['total']==0
        restored=c.post(f"/api/work-items/{item['id']}/restore",json={'expected_version':removed.json()['version']})
        assert restored.status_code==200
        report=c.post('/api/followup-reports',json={'project_id':project['id'],'start_date':today.date().isoformat(),'end_date':today.date().isoformat()})
        assert report.status_code==200,report.text
        for fmt in ('markdown','csv'):
            assert c.get(f"/api/followup-reports/{report.json()['id']}/export?format={fmt}").status_code==200
        checks.append('withdraw-restore-and-report-exports')
    return {'status':'passed','mode':'windows-native-offline' if native else 'macos-portable-offline','python':platform.python_version(),'checks':checks,'real_wechat':'not-tested','real_model':'not-tested','browser_tray':'not-tested'}

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    state=Path(os.getenv('LOCALAPPDATA',tempfile.gettempdir()))/'GroupChatOrganizer'
    state.mkdir(parents=True,exist_ok=True)
    if os.name=='nt':
        from app.platforms.windows_security import apply_current_user_acl
        apply_current_user_acl(state)
    try:
        with tempfile.TemporaryDirectory(prefix='self-test-',dir=state) as temporary:
            result=run_selftest(Path(temporary))
    except Exception as exc:
        import traceback
        frame=traceback.extract_tb(exc.__traceback__)[-1]
        result={'status':'failed','stage':'offline-self-test','error_type':type(exc).__name__,'location':Path(frame.filename).name+':'+str(frame.lineno),'real_wechat':'not-tested','real_model':'not-tested'}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    sys.exit(0 if result['status']=='passed' else 1)
