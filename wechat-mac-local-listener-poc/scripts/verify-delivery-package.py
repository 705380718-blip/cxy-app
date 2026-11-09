#!/usr/bin/env python3
"""Verify archive contents then start in a fresh, spaced path with offline dependencies."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime,timezone,timedelta
from pathlib import Path,PurePosixPath


def verify_archive(path,destination):
    with zipfile.ZipFile(path) as archive:
        names=archive.namelist()
        if len(names)!=len(set(names)) or sum(i.file_size for i in archive.infolist())>250_000_000:raise ValueError('重复文件或包体积异常')
        for i in archive.infolist():
            p=PurePosixPath(i.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in i.filename or stat.S_ISLNK(i.external_attr>>16):raise ValueError('不安全包路径')
            if any(v in p.parts for v in ('.env','private','backups','runtime','.venv')) or p.suffix in ('.db','.sqlite','.dpapi'):raise ValueError('包内含禁止分发数据')
        manifests=[n for n in names if n.endswith('/manifest.json')]
        if len(manifests)!=1:raise ValueError('缺少唯一清单')
        manifest=json.loads(archive.read(manifests[0]));prefix=manifests[0].removesuffix('manifest.json')
        if set(names)!={prefix+n for n in manifest['files']}|{manifests[0]}:raise ValueError('清单文件不一致')
        for n,digest in manifest['files'].items():
            if hashlib.sha256(archive.read(prefix+n)).hexdigest()!=digest:raise ValueError('包文件校验失败')
        archive.extractall(destination)
        return destination/prefix,manifest


def main():
    parser=argparse.ArgumentParser(description='核对分发清单并在临时干净目录启动/导入/报告 smoke');parser.add_argument('package',type=Path);parser.add_argument('--python',default=sys.executable);parser.add_argument('--port',type=int,default=8794);parser.add_argument('--output',type=Path,default=Path('output/package-verification.json'));args=parser.parse_args()
    if args.port in (5173,8000,8791,8792,8793) or not 1024<=args.port<=65535:parser.error('请选择独立验证端口，例如 8794')
    try:
        with socket.socket() as probe:probe.bind(('127.0.0.1',args.port))
        with tempfile.TemporaryDirectory(prefix='delivery clean smoke ') as temporary:
            root,manifest=verify_archive(args.package,Path(temporary));env=os.environ.copy()
            for name in list(env):
                if name.startswith(('WML_','DEEPSEEK_')):env.pop(name)
            env.update(WML_PYTHON=args.python,WML_PORT=str(args.port),WML_ENV_FILE=str(root/'delivery-local.env'),PIP_NO_INDEX='1')
            subprocess.run([args.python,'-c',"from pathlib import Path; from app.config import Settings; s=Settings.from_env(); assert s.database_path==Path.cwd()/'runtime/data/delivery.db'; assert s.decoder_command==(); assert str(s.wechat_data_root)=='runtime/empty-wechat'"],cwd=root,env=env,check=True,capture_output=True,timeout=5)
            log=root/'smoke.log';base=f'http://127.0.0.1:{args.port}'
            def request(path,data=None,method=None):
                req=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'},method=method)
                with urllib.request.urlopen(req,timeout=5) as r:
                    body=r.read();return json.loads(body) if 'application/json' in r.headers.get('Content-Type','') else body.decode('utf-8')
            with log.open('w') as handle:
                process=subprocess.Popen(['bash','start-delivery.sh'],cwd=root,env=env,stdout=handle,stderr=subprocess.STDOUT,start_new_session=True)
                try:
                    deadline=time.monotonic()+45
                    while True:
                        try:health=request('/api/health');break
                        except (OSError,ValueError):
                            if process.poll() is not None:raise ValueError('干净目录启动失败（日志保留至该次验证结束）')
                            if time.monotonic()>deadline:raise ValueError('启动超时')
                            time.sleep(.25)
                    subprocess.run([str(root/'.venv/bin/python'),'scripts/local_vault_decoder.py','--help'],cwd=root,env=env,check=True,capture_output=True,timeout=5)
                    subprocess.run([str(root/'.venv/bin/python'),'-c',"import zstandard; from scripts.local_vault_decoder import decode_value; text='compressed fixture'; assert decode_value(zstandard.ZstdCompressor().compress(text.encode()))==text"],cwd=root,env=env,check=True,capture_output=True,timeout=5)
                    assert health['version']==manifest['version'], 'health/manifest version mismatch'
                    if request('/api/ai/settings')['key_configured']:raise ValueError('干净包不应存在模型密钥')
                    setup=request('/api/workflow/setup',{'project_name':'构造样例-打包验收','groups':['构造样例-验收群'],'self_names':['构造助手'],'source_kind':'import'},'PUT')
                    project=setup['project'];source=setup['sources'][0]
                    assert setup['source_ready'] and setup['source_kind']=='import'
                    assert 'workflow.js' in request('/')
                    today=datetime.now(timezone(timedelta(hours=8))).date().isoformat();content=f'[{today} 09:00:00] 构造同事甲: 验收拓扑待补充，请问如何处理？'
                    preview=request('/api/imports/preview',{'project_source_id':source['id'],'format':'txt','content':content})
                    first=request(f"/api/imports/{preview['id']}/commit",{})
                    again=request(f"/api/imports/{preview['id']}/commit",{})
                    messages=request('/api/messages')['items'];assert len(messages)==1
                    item=request('/api/work-items',{'project_source_id':source['id'],'type':'task','title':'构造样例：补拓扑','evidence_message_ids':[messages[0]['id']]})
                    request(f"/api/work-items/{item['id']}",{'expected_version':1,'review_status':'confirmed'},'PATCH')
                    report=request('/api/followup-reports',{'project_id':project['id'],'start_date':today,'end_date':today})
                    assert report['coverage']['unanalysed_count']==1 and report['coverage']['analyzed_count']==0
                    assert '已确认事项' in request(f"/api/followup-reports/{report['id']}/export")
                    assert '脱敏依据' in request(f"/api/followup-reports/{report['id']}/export?format=csv")
                    inp=request(f"/api/evaluations/inputs?project_id={project['id']}")
                    evaluation=request('/api/evaluations',{'project_id':project['id'],'dataset_label':'构造样例包验证','scope_message_ids':[messages[0]['id']],'labels':[{'id':'L1','type':'issue','title':'拓扑未补','evidence_message_ids':[messages[0]['id']]}],'rule_reviews':[{'prediction_id':p['id'],'label_id':'L1'} for p in inp['rule_predictions']],'reviewer_label':'验收员A','attested':True})
                    assert not evaluation['metrics']['quality_goal_eligible'] and evaluation['metrics']['ai']['recall'] is None
                    assert '人工标注' in request(f"/api/evaluations/{evaluation['id']}/export")
                    with socket.socket() as occupied:
                        occupied.bind(('127.0.0.1',0));occupied.listen();blocked_env={**env,'WML_PORT':str(occupied.getsockname()[1])}
                        blocked=subprocess.run(['bash','start-delivery.sh'],cwd=root,env=blocked_env,capture_output=True,text=True,timeout=10)
                        assert blocked.returncode!=0 and '端口已占用' in blocked.stdout+blocked.stderr
                    result={'package':args.package.name,'sha256':hashlib.sha256(args.package.read_bytes()).hexdigest(),'manifest_file_count':len(manifest['files']),'platform':manifest['platform'],'python':manifest['python'],'fresh_venv':True,'offline_dependency_install':True,'decoder_cli_ready':True,'workflow_setup':True,'constructed_import':True,'duplicate_import_no_extra_messages':True,'manual_item':True,'report_and_csv':True,'evaluation_csv':True,'occupied_port_rejected':True,'real_key_present':False,'real_model_called':False,'interpreter_bundled':False}
                finally:
                    if process.poll() is None:
                        os.killpg(process.pid,signal.SIGTERM)
                        try:process.wait(timeout=8)
                        except subprocess.TimeoutExpired:os.killpg(process.pid,signal.SIGKILL);process.wait()
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps(result,ensure_ascii=False))
    except (OSError,ValueError,KeyError,AssertionError,subprocess.SubprocessError) as exc:parser.exit(1,f'[错误] 分发验收失败：{type(exc).__name__}。\n')

if __name__=='__main__':main()
