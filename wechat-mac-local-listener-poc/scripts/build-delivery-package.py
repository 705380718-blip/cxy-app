#!/usr/bin/env python3
"""Allowlisted, reproducible source + host wheels distribution; no runtime data."""
from __future__ import annotations
import argparse
import hashlib
import json
import platform
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
NAME='wechat-delivery-offline-0.5.7-macos-arm64'
FILES=['run.py','requirements-lock.txt','start-delivery.sh','start-delivery.command','delivery-guide.md','case-notes.md','scripts/evaluate-ai.py','scripts/serve-offline-delivery-demo.py','scripts/verify-delivery-package.py','scripts/local_vault_decoder.py','tools/verify_keys.py','tests/fixtures/delivery-evaluation.json']
# Generate a clean profile: never read a developer's editable environment file.
RELEASE_PROFILE = b'''WML_PLATFORM=macos
WML_HOST=127.0.0.1
WML_PORT=8792
WML_DATABASE_PATH=runtime/data/delivery.db
WML_WECHAT_APP=runtime/no-wechat.app
WML_WECHAT_DATA_ROOT=runtime/empty-wechat
WML_DECODER_COMMAND=[]
WML_AI_ENABLED=false
'''


def build(output,wheelhouse):
    files=[ROOT/f for f in FILES]+[p for p in (ROOT/'app').rglob('*') if p.is_file() and '__pycache__' not in p.parts and (p.suffix=='.py' or p.parent==ROOT/'app/static')]
    wheels=sorted(wheelhouse.glob('*.whl'))
    if not wheels:raise ValueError('缺少依赖 wheels，请先按 requirements-lock.txt 下载')
    entries={p.relative_to(ROOT).as_posix():p for p in files}
    entries.update({'wheelhouse/'+p.name:p for p in wheels})
    for name,p in entries.items():
        if not p.is_file() or p.is_symlink():raise ValueError('允许列表文件缺失或为符号链接：'+name)
        if any(part in ('private','runtime','.env','.venv','data','backups') for part in Path(name).parts) or p.suffix in ('.db','.sqlite','.dpapi'):raise ValueError('禁止分发运行数据：'+name)
    contents={name:p.read_bytes() for name,p in entries.items()}
    contents['delivery-local.env']=RELEASE_PROFILE
    manifest={'name':NAME,'version':'0.5.7','build_revision':'security-2026-10-12','python':'3.11','platform':'macOS arm64','interpreter_bundled':False,'real_model_trial':False,'files':{name:hashlib.sha256(data).hexdigest() for name,data in sorted(contents.items())}}
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in sorted(contents.items()):
            info=zipfile.ZipInfo(NAME+'/'+name,date_time=(2026,10,10,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=(0o100755 if name.startswith('start-delivery') else 0o100644)<<16
            archive.writestr(info,data)
        archive.writestr(NAME+'/manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    checksum=hashlib.sha256(output.read_bytes()).hexdigest();output.with_suffix('.zip.sha256').write_text(checksum+'  '+output.name+'\n')
    return {'path':str(output),'sha256':checksum,'file_count':len(contents)+1,'bytes':output.stat().st_size}


def main():
    parser=argparse.ArgumentParser(description='构建仅含允许列表源码和依赖的离线分发包');parser.add_argument('--output',type=Path,default=ROOT/'dist'/f'{NAME}.zip');parser.add_argument('--wheelhouse',type=Path,default=ROOT/'dist/wheelhouse');args=parser.parse_args()
    try:print(json.dumps(build(args.output,args.wheelhouse),ensure_ascii=False))
    except (OSError,ValueError) as exc:parser.exit(1,f'[错误] {exc}\n')

if __name__=='__main__':main()
