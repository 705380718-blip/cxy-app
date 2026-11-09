#!/usr/bin/env python3
"""Build a Windows x64 offline ZIP on any OS from hash-locked binary inputs."""
from __future__ import annotations
import argparse
import email
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import zipfile
from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = 'WML_PLATFORM=windows\nWML_HOST=127.0.0.1\nWML_PORT=8791\nWML_POLL_INTERVAL=0.5\nWML_ALLOW_UNVERIFIED_DECODER=false\nWML_WINDOWS_ACCOUNT_ID=\n'
RESERVED = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.I)

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def safe_member(name):
    path = PurePosixPath(name)
    if not name or name.startswith('/') or '\\' in name or ':' in name or any(p in ('..','.') or p.rstrip(' .') != p or RESERVED.match(p) for p in path.parts):
        raise ValueError('unsafe archive path')
    return path

def extract_verified(archive, destination, wheel=False):
    seen = set()
    with zipfile.ZipFile(archive) as source:
        if sum(i.file_size for i in source.infolist()) > 800_000_000:
            raise ValueError('archive too large')
        for info in source.infolist():
            path = safe_member(info.filename)
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError('archive symlinks are forbidden')
            if info.is_dir():
                continue
            parts = path.parts
            if wheel and parts[0].endswith('.data'):
                if len(parts) < 3 or parts[1] not in ('purelib','platlib'):
                    raise ValueError('unsupported wheel installation scheme')
                path = PurePosixPath(*parts[2:])
            key = str(path).casefold()
            target = destination.joinpath(*path.parts)
            if key in seen or target.exists():
                raise ValueError('duplicate archive destination')
            seen.add(key)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(info) as src, target.open('xb') as dst:
                shutil.copyfileobj(src, dst)

def validate_dependencies(lock, wheelhouse):
    environment = default_environment()
    environment.update(sys_platform='win32', os_name='nt', platform_system='Windows', platform_machine='AMD64', python_version='3.14', python_full_version='3.14.8', implementation_name='cpython', extra='')
    packages = {canonicalize_name(d['name']): d for d in lock['dependencies']}
    if len(packages) != len(lock['dependencies']):
        raise ValueError('duplicate dependency')
    for dependency in packages.values():
        name = dependency['filename']
        if safe_member(name).name != name:
            raise ValueError('wheel filename must be a basename')
        wheel = wheelhouse / name
        if digest(wheel) != dependency['sha256']:
            raise ValueError('wheel hash mismatch: '+name)
        with zipfile.ZipFile(wheel) as z:
            metadata = [n for n in z.namelist() if n.endswith('.dist-info/METADATA')]
            if len(metadata) != 1:
                raise ValueError('ambiguous wheel metadata')
            m = email.message_from_bytes(z.read(metadata[0]))
        if canonicalize_name(m['Name']) != canonicalize_name(dependency['name']) or m['Version'] != dependency['version']:
            raise ValueError('wheel identity mismatch')
        for value in m.get_all('Requires-Dist', []):
            requirement = Requirement(value)
            if requirement.marker and not requirement.marker.evaluate(environment):
                continue
            resolved = packages.get(canonicalize_name(requirement.name))
            if not resolved or resolved['version'] not in requirement.specifier:
                raise ValueError('unresolved Windows dependency: '+str(requirement))
    return list(packages.values())

def copy_file(source, destination):
    if source.is_symlink():
        raise ValueError('source links are forbidden')
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)

def build(runtime_zip, wheelhouse, output):
    locks = ROOT/'packaging/windows'
    runtime = json.loads((locks/'runtime-lock.json').read_text())
    lock = json.loads((locks/'dependencies-lock.json').read_text())
    if digest(runtime_zip) != runtime['sha256']:
        raise ValueError('Python runtime hash mismatch')
    dependencies = validate_dependencies(lock, wheelhouse)
    output.mkdir(parents=True, exist_ok=True)
    name = 'wechat-delivery-windows-0.5.7-local-20261012-x64'
    artifact = output/(name+'.zip')
    if artifact.exists():
        raise FileExistsError('output already exists; choose a new output directory')
    with tempfile.TemporaryDirectory(prefix='windows-build-') as temp:
        stage = Path(temp)/name
        stage.mkdir()
        for path in (ROOT/'app').rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix in ('.py','.js','.css','.html','.svg'):
                copy_file(path, stage/path.relative_to(ROOT))
        files = ['run.py','config/windows-decoder-profiles.json','scripts/windows_vault_decoder.py',
                 'tools/windows_key_prep.py','tools/windows_runtime.py','tools/windows_selftest.py',
                 'tools/export_legacy_windows.py','tools/verify_windows_package.py']
        for relative in files:
            copy_file(ROOT/relative, stage/relative)
        for basename in ('common.ps1','start-service.ps1','stop-service.ps1','tray.ps1','first-key-prep.ps1','clear-tool-data.ps1','self-test.ps1','export-legacy.ps1'):
            # Windows PowerShell 5.1 needs BOM to read Chinese text correctly.
            (stage/basename).write_text((locks/basename).read_text(encoding='utf-8-sig'),encoding='utf-8-sig')
        for basename in ('runtime-lock.json','dependencies-lock.json','windows-guide.md'):
            copy_file(locks/basename, stage/basename)
        (stage/'windows-default.env').write_text(DEFAULT_ENV, encoding='utf-8')
        commands = {'01-start':'start-service','02-stop':'stop-service','03-diagnose-and-key-prep':'first-key-prep','04-self-test':'self-test','05-export-legacy':'export-legacy','06-clear-tool-data':'clear-tool-data'}
        for filename, script in commands.items():
            (stage/(filename+'.cmd')).write_bytes(('@echo off\r\nsetlocal\r\n"%~dp0runtime\\python.exe" "%~dp0tools\\verify_windows_package.py"\r\nif errorlevel 1 (\r\n  pause\r\n  exit /b 1\r\n)\r\npowershell.exe -NoProfile -STA -File "%~dp0'+script+'.ps1"\r\nif errorlevel 1 (\r\n  pause\r\n  exit /b 1\r\n)\r\npause\r\n').encode('ascii'))
        extract_verified(runtime_zip, stage/'runtime')
        (stage/'runtime/python314._pth').write_text('python314.zip\n.\nLib/site-packages\n..\nimport sys; sys.dont_write_bytecode = True\n',encoding='ascii')
        for dependency in dependencies:
            extract_verified(wheelhouse/dependency['filename'], stage/'runtime/Lib/site-packages', wheel=True)
        sbom = {'bomFormat':'CycloneDX','specVersion':'1.5','version':1,'components':[{'type':'library','name':d['name'],'version':d['version'],'purl':f"pkg:pypi/{canonicalize_name(d['name'])}@{d['version']}",'hashes':[{'alg':'SHA-256','content':d['sha256']}]} for d in dependencies] + [{'type':'application','name':'CPython','version':runtime['version'],'hashes':[{'alg':'SHA-256','content':runtime['sha256']}],'externalReferences':[{'type':'distribution','url':runtime['url']}]}]}
        (stage/'sbom.cdx.json').write_text(json.dumps(sbom,indent=2)+'\n')
        manifest = {'product':'group-chat-organizer-local-listener','version':'0.5.7','build':'windows-local-20261012','native_validation':'pending','files':{p.relative_to(stage).as_posix():digest(p) for p in sorted(stage.rglob('*')) if p.is_file()}}
        (stage/'package-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
        with zipfile.ZipFile(artifact,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
            for path in sorted(stage.rglob('*')):
                if path.is_file():
                    info = zipfile.ZipInfo((Path(name)/path.relative_to(stage)).as_posix(),date_time=(2026,10,12,0,0,0))
                    info.compress_type = zipfile.ZIP_DEFLATED
                    info.external_attr = 0o100644 << 16
                    z.writestr(info,path.read_bytes())
    sha = digest(artifact)
    artifact.with_suffix('.zip.sha256').write_text(sha+'  '+artifact.name+'\n')
    return {'path':str(artifact),'sha256':sha,'bytes':artifact.stat().st_size,'dependencies':len(dependencies),'native_validation':'pending'}

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--runtime',type=Path,required=True)
    parser.add_argument('--wheelhouse',type=Path,required=True)
    parser.add_argument('--output',type=Path,default=ROOT/'dist/windows')
    args=parser.parse_args()
    print(json.dumps(build(args.runtime,args.wheelhouse,args.output),indent=2))
