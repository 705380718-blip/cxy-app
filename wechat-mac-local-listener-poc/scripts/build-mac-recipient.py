#!/usr/bin/env python3
"""Build a clean, relocatable, bundled-runtime macOS recipient package."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
NAME='wechat-delivery-mac-0.5.7-recipient-20261109-wx415-arm64'


def copy_runtime(source,destination):
    def ignore(directory,names):
        return [name for name in names if name in {'__pycache__','site-packages','test','tests','idlelib','tkinter','turtledemo','ensurepip'} or name.endswith('.pyc')]
    shutil.copytree(source/'lib',destination/'lib',ignore=ignore,symlinks=False)
    (destination/'bin').mkdir(parents=True)
    shutil.copy2(source/'bin/python3.11',destination/'bin/python3.11')
    (destination/'lib/python3.11/site-packages').mkdir(exist_ok=True)
    # uv patches its installation prefix locally. Remove publisher paths from the
    # copied runtime and keep sysconfig relative to the recipient's extraction path.
    config=destination/'lib/python3.11/_sysconfigdata__darwin_darwin.py'
    content=config.read_text().replace(str(source),'@BUNDLED_PYTHON@')
    content += "\nfrom pathlib import Path as _RuntimePath\n_runtime_prefix = str(_RuntimePath(__file__).resolve().parents[2])\nbuild_time_vars = {k: v.replace('@BUNDLED_PYTHON@', _runtime_prefix) if isinstance(v, str) else v for k, v in build_time_vars.items()}\n"
    config.write_text(content)
    library=destination/'lib/libpython3.11.dylib'
    subprocess.run(['/usr/bin/install_name_tool','-id','@rpath/libpython3.11.dylib',str(library)],check=True,capture_output=True)
    subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(library)],check=True,capture_output=True)


def build(runtime,output):
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='recipient-build-',dir=output) as tmp:
        bundle=Path(tmp)/NAME;bundle.mkdir()
        for directory in ['app']:
            shutil.copytree(ROOT/directory,bundle/directory,ignore=shutil.ignore_patterns('__pycache__','*.pyc'),symlinks=False)
        for name in ['run.py','requirements-lock.txt','scripts/local_vault_decoder.py','tools/verify_keys.py']:
            target=bundle/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
        template=ROOT/'packaging/mac-recipient'
        for name in ['recipient.py','mac_key_setup.py','decoder_guard.py']:
            shutil.copy2(template/name,bundle/'tools'/name)
        for name in ['start.command','manual.html','manual.pdf','read-first.txt','release-notes.md','requirements-setup.txt','third-party-notices.md']:
            shutil.copy2(template/name,bundle/name)
        (bundle/'start.command').chmod(0o755)
        copy_runtime(runtime,bundle/'python')
        target=bundle/'python/lib/python3.11/site-packages'
        subprocess.run([str(runtime/'bin/python3.11'),'-m','pip','install','--no-compile','--no-index',
                        '--find-links',str(ROOT/'dist/wheelhouse'),'--find-links',str(ROOT/'dist/mac-recipient-wheels'),
                        '--target',str(target),'-r',str(ROOT/'requirements-lock.txt'),'-r',str(template/'requirements-setup.txt')],check=True)
        # Installed console-script shebangs contain build-machine paths; launcher uses python -m / scripts directly.
        shutil.rmtree(target/'bin',ignore_errors=True)
        for p in bundle.rglob('__pycache__'):shutil.rmtree(p)
        env={k:v for k,v in os.environ.items() if not k.startswith(('PYTHON','WML_','DEEPSEEK_'))}
        env.update(PYTHONHOME=str(bundle/'python'),PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1')
        subprocess.run([str(bundle/'python/bin/python3.11'),'-c','import fastapi, uvicorn, frida, zstandard; from Crypto.Cipher import AES; import ssl, sqlite3; print("Bundled Python dependencies OK")'],cwd=bundle,env=env,check=True)
        contents={p.relative_to(bundle).as_posix():p for p in bundle.rglob('*') if p.is_file()}
        if any(p.is_symlink() for p in bundle.rglob('*')):raise ValueError('包内不能包含符号链接')
        forbidden={'.env','.venv','private','backups','data','output','vault'}
        for name in contents:
            if any(x in forbidden for x in Path(name).parts) or name.endswith(('.db','.sqlite','.dpapi')):
                raise ValueError('发现运行数据：'+name)
        personal_prefix=str(Path.home()).encode()
        if any(personal_prefix in p.read_bytes() for p in contents.values()):raise ValueError('运行时或文件中残留发布者个人路径')
        manifest={'name':NAME,'version':'0.5.7','build_revision':'recipient-20261109-wx415',
                  'platform':'macOS arm64','python':'3.11.15','interpreter_bundled':True,
                  'minimum_runtime_macos':'11','wechat_fresh_machine_verified':False,'candidate_wechat_builds':['4.1.15/270115'],
                  'files':{name:hashlib.sha256(p.read_bytes()).hexdigest() for name,p in sorted(contents.items())}}
        (bundle/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
        archive_path=output/(NAME+'.zip')
        with zipfile.ZipFile(archive_path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for p in sorted(bundle.rglob('*')):
                if p.is_file():
                    name=p.relative_to(bundle).as_posix()
                    info=zipfile.ZipInfo(NAME+'/'+name,(2026,11,9,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                    info.external_attr=(stat.S_IFREG | (0o755 if p.stat().st_mode&0o111 else 0o644))<<16
                    z.writestr(info,p.read_bytes())
        digest=hashlib.sha256(archive_path.read_bytes()).hexdigest()
        archive_path.with_suffix('.zip.sha256').write_text(digest+'  '+archive_path.name+'\n')
        return {'path':str(archive_path),'sha256':digest,'files':len(contents)+1,'bytes':archive_path.stat().st_size}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--runtime',type=Path,required=True);parser.add_argument('--output',type=Path,default=ROOT/'dist/mac-recipient-20261109')
    args=parser.parse_args();print(json.dumps(build(args.runtime,args.output),ensure_ascii=False))
