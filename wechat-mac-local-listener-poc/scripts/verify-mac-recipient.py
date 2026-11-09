#!/usr/bin/env python3
"""Verify exact recipient ZIP with bundled Python, isolated data and synthetic native capture."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime,timezone,timedelta

ROOT=Path(__file__).resolve().parents[1]


def extract_verified(package,destination):
    with zipfile.ZipFile(package) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or sum(i.file_size for i in z.infolist())>600_000_000:raise ValueError('archive limits')
        for item in z.infolist():
            p=PurePosixPath(item.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in item.filename or stat.S_ISLNK(item.external_attr>>16):raise ValueError('unsafe path')
        manifest_name=next(n for n in names if n.endswith('/manifest.json'))
        prefix=manifest_name.removesuffix('manifest.json');manifest=json.loads(z.read(manifest_name))
        assert set(names)=={prefix+n for n in manifest['files']}|{manifest_name}
        for name,digest in manifest['files'].items():assert hashlib.sha256(z.read(prefix+name)).hexdigest()==digest
        z.extractall(destination)
        for item in z.infolist():(destination/item.filename).chmod((item.external_attr>>16)&0o777 or 0o644)
        return destination/prefix,manifest


def native_capture_test(bundle,python,env,qa):
    fixture=qa/'synthetic-capture';fixture.mkdir(exist_ok=True)
    c=fixture/'derive.c';binary=fixture/'derive'
    c.write_text('''#include <CommonCrypto/CommonKeyDerivation.h>
#include <unistd.h>
int main(void) {
 unsigned char out[32];
 unsigned char salts[3][16]={{1},{2},{3}};
 for(int i=0;i<3;i++) CCKeyDerivationPBKDF(kCCPBKDF2,"fixture-only",12,salts[i],16,kCCPRFHmacAlgSHA512,1000,out,32);
 sleep(5);return 0;
}
''')
    subprocess.run(['/usr/bin/xcrun','clang',str(c),'-o',str(binary)],check=True,capture_output=True)
    harness=fixture/'test_capture.py'
    harness.write_text('''import sys, hashlib, struct
from pathlib import Path
sys.path.insert(0,str(Path(sys.argv[1])/'tools'))
sys.path.insert(0,sys.argv[1])
from Crypto.Cipher import AES
from mac_key_setup import collect_keys
root=Path(sys.argv[2]); dbs=[];expected={}
for number in (1,2):
 salt=bytes([number])+bytes(15);key=hashlib.pbkdf2_hmac('sha512',b'fixture-only',salt,1000,32)
 page=bytearray(4096);page[:16]=salt;page[16:18]=struct.pack('>H',4096);page[18:24]=bytes([1,1,80,64,32,32]);iv=b'i'*16
 page[16:4016]=AES.new(key,AES.MODE_CBC,iv).encrypt(bytes(page[16:4016]));page[4016:4032]=iv
 path=root/f'fixture-{number}.db';path.write_bytes(page);dbs.append(path);expected[path]=key.hex()
actual=collect_keys(root/'derive',dbs,timeout=15)
assert actual==expected
print('synthetic native capture: PASS; selected database salts only')
''')
    result=subprocess.run([str(python),str(harness),str(bundle),str(fixture)],env=env,capture_output=True,text=True,timeout=30)
    if result.returncode:raise AssertionError('native fixture failed: '+result.stdout+result.stderr)
    (qa/'native-capture.txt').write_text(result.stdout)


def verify(package,qa):
    qa.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='recipient clean path ') as name:
        clean=Path(name).resolve();bundle,manifest=extract_verified(package,clean)
        # Relocate once more to prove no build-time absolute path dependency.
        moved=clean/'Moved Package With Spaces';bundle.rename(moved);bundle=moved
        python=bundle/'python/bin/python3.11';store=clean/'Isolated User Data'
        env={k:v for k,v in os.environ.items() if not k.startswith(('WML_','DEEPSEEK_','PYTHON'))}
        env.update(PATH='/usr/bin:/bin',PYTHONHOME=str(bundle/'python'),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',WML_RECIPIENT_HOME=str(store))
        store.mkdir();(store/'config').mkdir()
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        config={'port':port,'collection':False};(store/'config/settings.json').write_text(json.dumps(config))
        def tool(action,*extra,ok=True):
            res=subprocess.run([str(python),str(bundle/'tools/recipient.py'),action,*extra],cwd=bundle,env=env,capture_output=True,text=True,timeout=35)
            if ok and res.returncode:raise AssertionError(action+': '+res.stdout+res.stderr)
            return res
        def request(path,data=None,method=None):
            req=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'},method=method)
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req,timeout=8) as r:
                payload=r.read();return json.loads(payload) if 'application/json' in r.headers.get('Content-Type','') else payload.decode()
        tool('check');tool('samples')
        try:
            tool('start','--no-open')
            assert request('/api/health')['version']==manifest['version']
            assert not request('/api/ai/settings')['key_configured']
            setup=request('/api/workflow/setup',{'project_name':'构造样例-接收方验收','groups':['构造测试群'],'self_names':['构造助手'],'source_kind':'import'},'PUT')
            source=setup['sources'][0];project=setup['project']
            preview=request('/api/imports/preview',{'project_source_id':source['id'],'format':'txt','content':(store/'samples/sample-chat.txt').read_text()})
            request(f"/api/imports/{preview['id']}/commit",{});request(f"/api/imports/{preview['id']}/commit",{})
            messages=request('/api/messages')['items'];assert len(messages)==2
            item=request('/api/work-items',{'project_source_id':source['id'],'type':'task','title':'构造样例：补充拓扑','evidence_message_ids':[messages[0]['id']]})
            request(f"/api/work-items/{item['id']}",{'expected_version':1,'review_status':'confirmed'},'PATCH')
            today=datetime.now(timezone(timedelta(hours=8))).date().isoformat()
            report=request('/api/followup-reports',{'project_id':project['id'],'start_date':today,'end_date':today})
            assert '已确认事项' in request(f"/api/followup-reports/{report['id']}/export")
            assert '脱敏依据' in request(f"/api/followup-reports/{report['id']}/export?format=csv")
            first_instance=request('/api/health')['instance_id']
            tool('start','--no-open');assert request('/api/health')['instance_id']==first_instance
            assert tool('backup',ok=False).returncode!=0
            tool('stop');tool('backup')
            backup=next((store/'backups').glob('*.zip'))
            tool('restore','--backup',str(backup));tool('start','--no-open')
            assert len(request('/api/messages')['items'])==2
            tool('stop')
            with socket.socket() as occupied:
                occupied.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
                occupied.bind(('127.0.0.1',port));occupied.listen()
                rejected=tool('start','--no-open',ok=False)
                assert rejected.returncode!=0 and '端口' in rejected.stdout+rejected.stderr
            tool('diagnose')
            diag=(store/'support/diagnostic.json').read_text()
            assert 'api_key' not in diag and str(store) not in diag
            native_capture_test(bundle,python,env,qa)
            result={'package':package.name,'sha256':hashlib.sha256(package.read_bytes()).hexdigest(),
                    'manifest_files':len(manifest['files']),'bundled_runtime':True,'system_python_not_used':True,
                    'moved_path_with_spaces':True,'environment_check':True,'sample_import':True,'duplicate_import':True,
                    'manual_task_report_csv':True,'idempotent_start':True,'stop_and_restart':True,
                    'backup_restore':True,'occupied_port_rejected':True,'redacted_diagnostic':True,
                    'synthetic_native_key_capture':True,'real_wechat_touched':False,'real_model_called':False,
                    'second_mac_tested':False,'macos_tested':subprocess.check_output(['/usr/bin/sw_vers','-productVersion'],text=True).strip()}
        finally:tool('stop',ok=False)
        (qa/'package-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('package',type=Path);p.add_argument('--output',type=Path,default=ROOT/'output/mac-recipient-20261109');args=p.parse_args()
    print(json.dumps(verify(args.package,args.output),ensure_ascii=False))
