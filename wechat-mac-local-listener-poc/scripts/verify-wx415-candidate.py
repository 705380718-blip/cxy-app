#!/usr/bin/env python3
"""Exercise the packaged candidate gate and decoder with a synthetic encrypted fixture."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'tests'))
from test_mac_recipient import make_encrypted_schema_fixture
spec=importlib.util.spec_from_file_location('package_qa',ROOT/'scripts/verify-mac-recipient.py')
qa=importlib.util.module_from_spec(spec);spec.loader.exec_module(qa)

HARNESS=r'''
import json, os, plistlib, subprocess, sys
from pathlib import Path
bundle=Path(sys.argv[1]);base=Path(sys.argv[2]);sys.path.insert(0,str(bundle/'tools'))
import recipient as r
fixture=json.loads((base/'fixture.json').read_text());db=Path(fixture['db']);keys=fixture['keys']
r.STORE=base/'state';r.private_dir(r.STORE)
app=base/'WeChat.app';(app/'Contents').mkdir(parents=True)
(app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':'4.1.15','CFBundleVersion':'270115'}))
assert r.require_supported(app)==('4.1.15','270115')
keys=r.validate_keys(db,keys)
cfg={'collection':True,'port':8795,'wechat_app':str(app),'wechat_version':['4.1.15','270115'],'db_base':str(db)}
r.save_json(r.STORE/'config/wechat-keys.json',keys)
r.save_json(r.STORE/'config/settings.json',cfg)
try:r.write_env(cfg)
except ValueError:pass
else:raise AssertionError('candidate bypassed local validation')
args=[sys.executable,str(bundle/'tools/decoder_guard.py'),'--wechat-app',str(app),'--wechat-version','4.1.15','--wechat-build','270115','--validation-config',str(r.STORE/'config/settings.json'),'new-messages','--db-base',str(db),'--keys',str(r.STORE/'config/wechat-keys.json'),'--vault',str(r.STORE/'vault')]
env={**os.environ,'WML_TARGET_GROUPS_JSON':json.dumps(['构造测试群'],ensure_ascii=False)}
blocked=subprocess.run(args,cwd=bundle,env=env,capture_output=True,text=True,timeout=15)
assert blocked.returncode!=0
summary=r.validate_local_databases(db,keys)
cfg['local_validation']={'profile':r.COMPATIBILITY_PROFILE,'status':'database-validated','binding':r.compatibility_binding('4.1.15','270115',db,keys),**summary}
r.save_json(r.STORE/'config/settings.json',cfg)
r.write_env(cfg)
result=subprocess.run(args,cwd=bundle,env=env,capture_output=True,text=True,timeout=15)
assert result.returncode==0,result.stderr
messages=json.loads(result.stdout)['messages']
assert len(messages)==1 and messages[0]['content']=='构造编号 WX415-001'
repeat=subprocess.run(args,cwd=bundle,env=env,capture_output=True,text=True,timeout=15)
assert json.loads(repeat.stdout)['messages'][0]['source_id']==messages[0]['source_id']
(app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':'4.1.15','CFBundleVersion':'270116'}))
changed=subprocess.run(args,cwd=bundle,env=env,capture_output=True,text=True,timeout=15)
assert changed.returncode!=0
print(json.dumps({'candidate_start_requires_receipt':True,'candidate_decoder_requires_receipt':True,'encrypted_fixture_validated':True,'packaged_decoder_message':True,'stable_source_id':True,'changed_build_blocked':True,'real_270115_tested':False}))
'''

if __name__=='__main__':
    package=Path(sys.argv[1]).resolve()
    with tempfile.TemporaryDirectory(prefix='wx415 candidate qa ') as td:
        base=Path(td).resolve();bundle,manifest=qa.extract_verified(package,base)
        db,keys=make_encrypted_schema_fixture(base/'synthetic')
        (base/'fixture.json').write_text(json.dumps({'db':str(db),'keys':keys}))
        harness=base/'harness.py';harness.write_text(HARNESS)
        env={k:v for k,v in os.environ.items() if not k.startswith(('WML_','DEEPSEEK_','PYTHON'))}
        env.update(PATH='/usr/bin:/bin',PYTHONHOME=str(bundle/'python'),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
        result=subprocess.run([str(bundle/'python/bin/python3.11'),str(harness),str(bundle),str(base)],env=env,cwd=bundle,capture_output=True,text=True,timeout=40)
        if result.returncode:raise AssertionError(result.stdout+result.stderr)
        data=json.loads(result.stdout);data['package']=package.name
        output=ROOT/'output/mac-recipient-20261109/candidate-verification.json'
        output.write_text(json.dumps(data,ensure_ascii=False,indent=2));print(json.dumps(data,ensure_ascii=False))
