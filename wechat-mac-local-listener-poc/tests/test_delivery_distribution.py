import importlib.util
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from app.config import Settings,PROJECT_ROOT


def module(name):
    spec=importlib.util.spec_from_file_location('delivery_'+name,PROJECT_ROOT/'scripts'/f'{name}.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_release_profile_uses_project_local_database(monkeypatch):
    for key in list(os.environ):
        if key.startswith('WML_'):monkeypatch.delenv(key)
    monkeypatch.setenv('WML_ENV_FILE',str(PROJECT_ROOT/'delivery-local.env'))
    s=Settings.from_env();assert s.database_path==PROJECT_ROOT/'runtime/data/delivery.db'
    assert s.wechat_data_root==Path('runtime/empty-wechat') and s.decoder_command==()
    assert s.wechat_app_path==Path('runtime/no-wechat.app')


@pytest.mark.parametrize('mode',['rules','mock'])
def test_constructed_cli_no_real_call(tmp_path,mode):
    env={k:v for k,v in os.environ.items() if not k.startswith(('WML_','DEEPSEEK_'))}
    r=subprocess.run([sys.executable,'scripts/evaluate-ai.py','--mode',mode,'--output',str(tmp_path/'results')],cwd=PROJECT_ROOT,env=env,capture_output=True,text=True,timeout=15)
    assert r.returncode==0,r.stderr
    data=json.loads((tmp_path/'results/evaluation.json').read_text());assert data['mode']=='simulated' and not data['metrics']['quality_goal_eligible']
    if mode=='mock':assert data['metrics']['mock_detected'] and data['metrics']['ai']['true_positive']==3
    else:assert data['metrics']['ai']['recall'] is None


def test_cli_deepseek_requires_explicit_consent(tmp_path):
    env={**os.environ,'DEEPSEEK_API_KEY':'fixture-only'}
    r=subprocess.run([sys.executable,'scripts/evaluate-ai.py','--mode','deepseek','--output',str(tmp_path)],cwd=PROJECT_ROOT,env=env,capture_output=True,text=True,timeout=5)
    assert r.returncode!=0 and 'consent-deepseek' in r.stderr
    assert 'fixture-only' not in r.stdout+r.stderr and not (tmp_path/'evaluation.json').exists()


@pytest.mark.parametrize('name',['../outside.py','/outside.py','safe/../../outside.py','safe\\outside.py','safe/runtime/data.db'])
def test_archive_blocks_traversal_and_runtime_data(tmp_path,name):
    path=tmp_path/'bad.zip'
    with zipfile.ZipFile(path,'w') as archive:archive.writestr(name,'not real data')
    with pytest.raises(ValueError):module('verify-delivery-package').verify_archive(path,tmp_path/'extract')


def test_archive_requires_manifest_and_hash(tmp_path):
    path=tmp_path/'bad.zip'
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('safe/code.py','abc');archive.writestr('safe/manifest.json',json.dumps({'files':{'code.py':'wrong'}}))
    with pytest.raises(ValueError,match='校验'):module('verify-delivery-package').verify_archive(path,tmp_path/'extract')


def test_package_builder_requires_wheels(tmp_path):
    with pytest.raises(ValueError,match='wheels'):module('build-delivery-package').build(tmp_path/'package.zip',tmp_path/'none')


def test_package_uses_generated_profile_not_local_credentials(tmp_path, monkeypatch):
    builder=module('build-delivery-package')
    root=tmp_path/'source';root.mkdir()
    for name in builder.FILES:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture')
    (root/'delivery-local.env').write_text('DEEPSEEK_API_KEY=fixture-private-key\nWML_DECODER_COMMAND=["unsafe"]')
    wheels=tmp_path/'wheels';wheels.mkdir();(wheels/'fixture.whl').write_bytes(b'fixture')
    monkeypatch.setattr(builder,'ROOT',root)
    output=tmp_path/'package.zip';builder.build(output,wheels)
    with zipfile.ZipFile(output) as archive:
        profile=archive.read(builder.NAME+'/delivery-local.env')
        assert profile==builder.RELEASE_PROFILE and b'fixture-private-key' not in profile
        assert b'WML_DECODER_COMMAND=[]' in profile
    extracted,manifest=module('verify-delivery-package').verify_archive(output,tmp_path/'extract')
    assert (extracted/'delivery-local.env').read_bytes()==profile
