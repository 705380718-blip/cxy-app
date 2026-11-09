#!/usr/bin/env python3
"""Recipient lifecycle tools. Operates only on its own private application directory."""
from __future__ import annotations
import argparse
import contextlib
import csv
import fcntl
import hashlib
import json
import os
import platform
import plistlib
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.verify_keys import key_works

BUILD = 'recipient-20261109-wx415'
RESTORABLE_BUILDS = {'recipient-20261105', BUILD}
SUPPORTED = {'4.1.11.55': None, '4.1.12': '269341', '4.1.13': '269629'}
# Candidate builds may enter local validation, never bypass it.
CANDIDATE_BUILDS = {('4.1.15', '270115')}
COMPATIBILITY_PROFILE = 'mac-sqlcipher4-message-v1'
APP = Path('/Applications/WeChat.app')
DEFAULT_HOME = Path.home() / 'Library/Application Support/交付小助手-mac'
STORE = Path(os.environ.get('WML_RECIPIENT_HOME', str(DEFAULT_HOME))).absolute()
PYTHON = ROOT / 'python/bin/python3.11'
STATE_DIRS = ('config', 'data')


def private_dir(path):
    path = Path(path)
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('数据路径中存在符号链接，请选择普通本地目录。')
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def save_json(path, data):
    path = Path(path)
    private_dir(path.parent)
    if path.is_symlink():
        raise ValueError('配置文件是链接，拒绝覆盖。')
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.write-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_json(path, fallback=None):
    return json.loads(Path(path).read_text()) if Path(path).exists() else fallback


def settings():
    return read_json(STORE/'config/settings.json', {'port':8792, 'collection':False})


def required_databases(db):
    db = Path(db)
    messages = sorted((db/'message').glob('message_[0-9]*.db'))
    if not messages or not (db/'contact/contact.db').is_file():
        raise ValueError('账号缺少联系人或消息数据库。请在官方微信登录并打开测试群后重试。')
    return [db/'contact/contact.db', *messages]


def validate_keys(db, keys):
    if not isinstance(keys, dict):
        raise ValueError('密钥文件格式不正确。')
    normalized = {}
    for path in required_databases(db):
        relative = path.relative_to(db).as_posix()
        key = keys.get(relative) or keys.get(path.stem)
        if not isinstance(key, str) or not key_works(path, key):
            raise ValueError('联系人或消息分片密钥验证失败，未保存配置。请重新准备。')
        normalized[relative] = key
    return normalized


def wechat_version(app=APP):
    with (app/'Contents/Info.plist').open('rb') as f:
        data = plistlib.load(f)
    return str(data.get('CFBundleShortVersionString','')), str(data.get('CFBundleVersion',''))


def require_supported(app=APP):
    version, build = wechat_version(app)
    if (version, build) not in CANDIDATE_BUILDS and (version not in SUPPORTED or SUPPORTED[version] not in (None, build)):
        raise ValueError(f'微信 {version} ({build}) 不在已登记兼容范围，已阻止采集配置。可先使用手动导入，联系发布者适配。')
    return version, build


def compatibility_binding(version, build, db, keys):
    material = json.dumps([version, build, str(Path(db).resolve()), keys], sort_keys=True)
    return hashlib.sha256(material.encode()).hexdigest()


def require_local_validation(config, db, keys):
    version, build = config['wechat_version']
    if (version, build) not in CANDIDATE_BUILDS:
        return
    receipt = config.get('local_validation', {})
    if (receipt.get('profile') != COMPATIBILITY_PROFILE
            or receipt.get('binding') != compatibility_binding(version, build, db, keys)
            or receipt.get('status') != 'database-validated'):
        raise ValueError('4.1.15 必须先完成本机数据库兼容性验证，请重新执行“首次配置”。')


def inspect_decrypted_schema(path, *, contact=False):
    """Check exactly the SQL columns consumed by the reader; never return messages."""
    from scripts.local_vault_decoder import decode_value
    with sqlite3.connect(f'{Path(path).as_uri()}?mode=ro', uri=True) as conn:
        if conn.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('数据库完整性校验失败。')
        if contact:
            conn.execute('SELECT username, nick_name, remark, alias FROM contact LIMIT 0')
            return 0
        conn.execute('SELECT rowid, user_name FROM Name2Id LIMIT 0')
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                  if re.fullmatch(r'Msg_[0-9a-fA-F]{32}', row[0])]
        for table in tables:
            rows = conn.execute(f'SELECT local_id, server_id, local_type, real_sender_id, '
                                f'create_time, message_content, compress_content FROM [{table}] LIMIT 1')
            for row in rows:
                int(row[0]); int(row[3] or 0); int(row[4])
                for value in row[5:]:
                    if decode_value(value) == '[压缩消息解码失败]':
                        raise ValueError('消息压缩格式验证失败。')
        return len(tables)


def validate_local_databases(db, keys):
    from scripts.local_vault_decoder import decrypt_snapshot
    database_count = 0
    message_tables = 0
    try:
        with tempfile.TemporaryDirectory(dir=private_dir(STORE/'tmp'), prefix='validate-') as temporary:
            for database in required_databases(db):
                relative = database.relative_to(db).as_posix()
                output = Path(temporary)/relative
                decrypt_snapshot(database, output, keys[relative])
                message_tables += inspect_decrypted_schema(output, contact=database.stem == 'contact')
                database_count += 1
    except (sqlite3.Error, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise ValueError('解密完整性或消息表结构未通过，未启用采集。请用菜单 10 导出脱敏诊断给发布者。') from None
    if message_tables == 0:
        raise ValueError('未发现可读取的消息表。请先在官方微信打开测试群，再重新配置。')
    return {'databases_checked': database_count, 'message_tables_checked': message_tables}


def compatibility_status(stage, status='running', **summary):
    # This report must never contain paths, account identifiers, message text or keys.
    report = read_json(STORE/'support/compatibility.json', {})
    report.update(stage=stage, status=status, updated_at=datetime.now(timezone.utc).isoformat())
    report.update({key: value for key, value in summary.items()
                   if key in {'wechat_version', 'databases_checked', 'message_tables_checked'}})
    save_json(STORE/'support/compatibility.json', report)


def verify_collection(config):
    version, build = require_supported(Path(config['wechat_app']))
    if [version, build] != config['wechat_version']:
        raise ValueError('微信版本发生变化，请重新执行首次配置。')
    db = Path(config['db_base'])
    keys = validate_keys(db, read_json(STORE/'config/wechat-keys.json', {}))
    require_local_validation(config, db, keys)
    return db


def choose_path(prompt, folder=False):
    expression = f'POSIX path of (choose {"folder" if folder else "file"} with prompt {json.dumps(prompt,ensure_ascii=False)})'
    result = subprocess.run(['/usr/bin/osascript','-e',expression], capture_output=True, text=True)
    if result.returncode:
        raise ValueError('已取消选择。')
    return Path(result.stdout.strip())


def ask(prompt):
    return input(prompt).strip()


def confirm(prompt):
    if ask(prompt+' 输入 YES 继续：') != 'YES':
        raise ValueError('已取消，未执行该操作。')


def process_record():
    return read_json(STORE/'service.json', {})


def health(port):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://127.0.0.1:{port}/api/health', timeout=2) as response:
        return json.load(response)


def owned_process(record):
    if not record or not isinstance(record.get('pid'), int):
        return False
    try:
        p = subprocess.run(['/bin/ps','-p',str(record['pid']),'-o','command='],capture_output=True,text=True,timeout=3)
        command = p.stdout.strip()
        return p.returncode == 0 and command == record.get('command') and record.get('run_path','') in command
    except OSError:
        return False


def require_stopped():
    if owned_process(process_record()):
        raise ValueError('请先使用“停止服务”，再执行配置、备份或恢复。')


def write_env(config):
    port = int(config.get('port',8792))
    if port in (5173,8000) or not 1024 <= port <= 65535:
        raise ValueError('端口须为 1024–65535，不能使用保留端口 5173/8000。')
    decoder=[]
    app='runtime/no-wechat.app'; data_root='runtime/empty-wechat'
    version='4.1.12'
    if config.get('collection'):
        db=verify_collection(config)
        app=config['wechat_app']; data_root=str(db.parent.parent)
        version=config['wechat_version'][0]
        decoder=[str(PYTHON), str(ROOT/'tools/decoder_guard.py'),'--wechat-app',app,'--wechat-version',config['wechat_version'][0],
                 '--wechat-build',config['wechat_version'][1],'--validation-config',str(STORE/'config/settings.json'),'new-messages',
                 '--db-base',str(db),'--keys',str(STORE/'config/wechat-keys.json'),
                 '--vault',str(STORE/'vault'),'--limit','200']
    values={'WML_PLATFORM':'macos','WML_HOST':'127.0.0.1','WML_PORT':str(port),
            'WML_DATABASE_PATH':str(STORE/'data/delivery.db'),'WML_WECHAT_APP':app,
            'WML_WECHAT_DATA_ROOT':data_root,'WML_DECODER_COMMAND':json.dumps(decoder,ensure_ascii=False),
            'WML_MAX_VERIFIED_WECHAT_VERSION':version,'WML_ALLOW_UNVERIFIED_DECODER':'false'}
    if any('\n' in value or '\r' in value for value in values.values()):
        raise ValueError('配置路径不能包含换行。')
    private_dir(STORE/'config'); private_dir(STORE/'data'); private_dir(STORE/'logs'); private_dir(STORE/'vault')
    envfile=STORE/'config/runtime.env'
    if envfile.is_symlink() or (STORE/'data/delivery.db').is_symlink():
        raise ValueError('运行文件包含链接，已拒绝启动。')
    envfile.write_text('\n'.join(f'{key}={value}' for key,value in values.items())+'\n')
    envfile.chmod(0o600)
    return envfile, port


def child_env():
    env={k:v for k,v in os.environ.items() if not k.startswith(('WML_','DEEPSEEK_','PYTHON'))}
    env.update(PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',PYTHONHOME=str(ROOT/'python'),PYTHONUNBUFFERED='1')
    return env


def check_environment():
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('此包仅支持 Apple Silicon Mac，请勿通过 Intel/Rosetta Python 运行。')
    if sys.version_info[:2] != (3,11):
        raise ValueError('请使用软件包内的启动入口。')
    if tuple(map(int,platform.mac_ver()[0].split('.')[:1])) < (11,):
        raise ValueError('此运行时最低要求 macOS 11，具体微信客户端可能要求更高版本。')
    for name in ['fastapi','uvicorn','Crypto.Cipher.AES','zstandard','frida']:
        __import__(name)
    print(f'运行环境正常：macOS {platform.mac_ver()[0]} / Apple Silicon / Python {platform.python_version()}')
    if APP.exists():
        print('微信版本：'+' / '.join(wechat_version()))
    else: print('未找到应用程序目录中的微信；仍可使用手动导入。')
    print('采集配置：'+('已配置（启动时重新校验）' if settings().get('collection') else '未配置；导入模式可用'))


def start_service(open_browser=True):
    check_environment()
    record=process_record()
    if owned_process(record):
        if health(record['port']).get('instance_id') != record['instance']:
            raise ValueError('服务身份不一致，请检查端口，未终止任何进程。')
        port=record['port']
    else:
        config=settings(); envfile,port=write_env(config)
        with socket.socket() as sock:
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            try: sock.bind(('127.0.0.1',port))
            except OSError: raise ValueError(f'端口 {port} 已占用。请使用菜单修改端口。')
        env=child_env(); instance=secrets.token_hex(16)
        env.update(WML_ENV_FILE=str(envfile),WML_PYTHON=str(PYTHON),WML_INSTANCE_ID=instance)
        log=STORE/'logs/service.log'
        if log.exists() and log.stat().st_size > 5_000_000:
            log.replace(STORE/'logs/service-previous.log')
        run=ROOT/'run.py'
        with log.open('ab') as f:
            process=subprocess.Popen([str(PYTHON),str(run)],cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
        log.chmod(0o600)
        try:
            command=subprocess.check_output(['/bin/ps','-p',str(process.pid),'-o','command='],text=True).strip()
            record={'pid':process.pid,'port':port,'instance':instance,'command':command,'run_path':str(run)}
            save_json(STORE/'service.json',record)
            for _ in range(80):
                if process.poll() is not None: raise ValueError('服务启动失败。请查看本机日志，反馈前移除个人路径和正文。')
                try:
                    if health(port).get('instance_id') == instance: break
                except (OSError,ValueError): pass
                time.sleep(.25)
            else: raise ValueError('服务启动超时，请检查日志。')
        except BaseException:
            if process.poll() is None: process.terminate(); process.wait(timeout=10)
            (STORE/'service.json').unlink(missing_ok=True)
            raise
    url=f'http://127.0.0.1:{port}/'
    print(f'服务已启动：{url}\n现在可关闭此终端；服务仍在后台运行。停止请使用菜单中的“停止服务”。')
    if open_browser: subprocess.run(['/usr/bin/open',url],check=True)
    return record


def stop_service():
    record=process_record()
    if not owned_process(record):
        print('未发现本工具管理的运行进程。'); return
    os.kill(record['pid'],signal.SIGTERM)
    for _ in range(60):
        if not owned_process(record): break
        time.sleep(.2)
    else: raise ValueError('服务尚未退出，请稍后重试；未强制杀死进程。')
    (STORE/'service.json').unlink(missing_ok=True)
    print('服务已停止。')


def initial_setup():
    try:
        _initial_setup()
    except (ValueError, OSError, sqlite3.Error, subprocess.SubprocessError):
        report = read_json(STORE/'support/compatibility.json', {})
        compatibility_status(report.get('stage', 'environment'), 'failed')
        raise


def _initial_setup():
    compatibility_status('environment')
    require_stopped(); check_environment()
    print('1 仅使用聊天文件导入\n2 配置本机微信监听')
    mode=ask('选择：')
    cfg=settings()
    if mode=='1':
        cfg['collection']=False; save_json(STORE/'config/settings.json',cfg)
        compatibility_status('import-mode', 'configured')
        print('已设为导入模式。'); return
    if mode!='2': raise ValueError('无效选项。')
    compatibility_status('version', wechat_version=list(wechat_version()))
    version,build=require_supported()
    if (version, build) in CANDIDATE_BUILDS:
        print('微信 4.1.15（270115）已进入兼容性验证流程。须完成密钥、完整性及消息结构验证，才能启用采集。')
    compatibility_status('account-selection')
    base=Path.home()/'Library/Containers/com.tencent.xinWeChat/Data/Documents/xwechat_files'
    accounts=sorted(base.glob('*/db_storage'))
    if not accounts:
        raise ValueError('未发现本机微信账号。请登录官方微信并打开群聊；权限受限时按手册检查终端文件访问权限。')
    for i,path in enumerate(accounts,1): print(f'{i}. {path.parent.name}')
    index=int(ask('选择当前微信账号编号：'))-1
    if index not in range(len(accounts)): raise ValueError('账号编号无效。')
    db=accounts[index]; required_databases(db)
    print('1 导入自己已有的微信密钥 JSON\n2 在此电脑首次准备（需临时微信副本）')
    mode=ask('选择：')
    compatibility_status('key-preparation')
    if mode=='1':
        keys=validate_keys(db,read_json(choose_path('选择你本人此账号的微信密钥 JSON')))
    elif mode=='2':
        confirm('首次准备会复制并临时签名微信副本、启动该副本以获取你本人账号的本地数据库密钥。密钥仅保存在本机。请先手动退出官方微信。')
        from mac_key_setup import capture_from_copy
        keys=capture_from_copy(APP,db,STORE)
    else: raise ValueError('无效选项。')
    keys=validate_keys(db,keys)
    compatibility_status('database-validation')
    summary = validate_local_databases(db, keys)
    save_json(STORE/'config/wechat-keys.json',keys)
    receipt = {'profile': COMPATIBILITY_PROFILE, 'binding': compatibility_binding(version, build, db, keys),
               'status': 'database-validated', 'verified_at': datetime.now(timezone.utc).isoformat(), **summary}
    cfg.update(collection=True,wechat_app=str(APP),wechat_version=[version,build],db_base=str(db),local_validation=receipt)
    save_json(STORE/'config/settings.json',cfg)
    compatibility_status('database-validated', 'passed-awaiting-live-message', **summary)
    print('数据库验证完成。请重新打开官方微信，再启动本工具、填写精确群名并点击“开始采集”。\n还需在测试群发送唯一编号消息，确认新消息确实到达。')


def sample_files():
    directory=private_dir(STORE/'samples')
    now=datetime.now(timezone(timedelta(hours=8)))
    stamp=now.strftime('%Y-%m-%d %H:%M:%S')
    sample=[('构造客户甲','验收说明缺少拓扑，请补充。'),('构造同事乙','我负责今天补齐拓扑并提交。')]
    (directory/'sample-chat.txt').write_text(''.join(f'[{stamp}] {person}: {body}\n' for person,body in sample))
    with (directory/'sample-chat.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['source_message_id','timestamp','sender','content'])
        for i,(person,body) in enumerate(sample):writer.writerow([f'fixture-{now:%Y%m%d%H%M%S}-{i}',stamp,person,body])
    print('今日构造样例已生成；TXT 与 CSV 二选一导入，避免把两种格式当成同一批消息。')
    return directory


def backup_state():
    require_stopped()
    directory=private_dir(STORE/'backups')
    dest=directory/f'backup-{datetime.now():%Y%m%d-%H%M%S}-{secrets.token_hex(3)}.zip'
    entries={}
    for top in STATE_DIRS:
        for p in (STORE/top).rglob('*'):
            if p.is_symlink(): raise ValueError('数据中发现链接，备份已停止。')
            if p.is_file() and not p.name.endswith(('-wal','-shm')) and p.name!='runtime.env':
                if 'session' not in p.parts: entries[p.relative_to(STORE).as_posix()]=p
    if not entries: raise ValueError('还没有可备份数据。')
    manifest={'format':1,'build':BUILD,'created_at':datetime.now().isoformat(),'files':{}}
    with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,p in entries.items():
            if p.suffix=='.db':
                with tempfile.TemporaryDirectory(dir=directory) as temporary:
                    snap=Path(temporary)/'snapshot.db'
                    with sqlite3.connect(f'{p.as_uri()}?mode=ro',uri=True) as src,sqlite3.connect(snap) as out: src.backup(out)
                    payload=snap.read_bytes()
            else: payload=p.read_bytes()
            archive.writestr(name,payload);manifest['files'][name]=hashlib.sha256(payload).hexdigest()
        archive.writestr('backup-manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    dest.chmod(0o600)
    print('本机备份已创建。备份可能包含聊天和两类密钥，不要作为软件安装包转发。')
    return dest


def validate_backup(archive_path, staging):
    with zipfile.ZipFile(archive_path) as archive:
        infos=archive.infolist();names=[i.filename for i in infos]
        if len(names)!=len(set(names)) or len(names)>20000 or sum(i.file_size for i in infos)>2_000_000_000:
            raise ValueError('备份重复项或大小超限。')
        for i in infos:
            p=PurePosixPath(i.filename)
            if p.is_absolute() or '..' in p.parts or '\\' in i.filename or stat.S_ISLNK(i.external_attr>>16):
                raise ValueError('备份路径不安全。')
            if i.filename!='backup-manifest.json' and (not p.parts or p.parts[0] not in STATE_DIRS):
                raise ValueError('备份包含非本工具数据。')
        manifest=json.loads(archive.read('backup-manifest.json'))
        if manifest.get('format')!=1 or manifest.get('build') not in RESTORABLE_BUILDS:
            raise ValueError('备份版本不匹配。请先使用对应版本恢复，再按升级说明迁移。')
        if set(names)!=set(manifest['files'])|{'backup-manifest.json'}:raise ValueError('备份清单不一致。')
        for name,digest in manifest['files'].items():
            content=archive.read(name)
            if hashlib.sha256(content).hexdigest()!=digest:raise ValueError('备份校验失败。')
            target=staging/name;private_dir(target.parent);target.write_bytes(content);target.chmod(0o600)
    for database in staging.rglob('*.db'):
        with sqlite3.connect(f'{database.as_uri()}?mode=ro',uri=True) as conn:
            if conn.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('备份数据库校验失败。')
            from app.delivery_schema import SCHEMA_VERSION
            if conn.execute('PRAGMA user_version').fetchone()[0]>SCHEMA_VERSION:raise ValueError('备份数据库来自更新版本，不能降级恢复。')
    return manifest


def restore_state(path):
    require_stopped()
    private_dir(STORE/'tmp')
    with tempfile.TemporaryDirectory(dir=STORE/'tmp',prefix='restore-') as name:
        staged=Path(name);validate_backup(path,staged)
        if any((STORE/top).exists() for top in STATE_DIRS): backup_state()
        previous=private_dir(staged/'previous')
        moved=[];installed=[]
        try:
            for top in STATE_DIRS:
                dest=STORE/top
                if dest.exists(): dest.rename(previous/top);moved.append(top)
                if (staged/top).exists(): (staged/top).rename(dest);installed.append(top)
        except BaseException:
            for top in installed: shutil.rmtree(STORE/top)
            for top in moved: (previous/top).rename(STORE/top)
            raise
    print('恢复完成；旧数据已预先备份。启动时会重新校验微信版本和密钥。')


def migrate_legacy(folder):
    require_stopped()
    if (STORE/'data/delivery.db').exists(): raise ValueError('当前已有业务库，不能直接覆盖；请另行处理合并或恢复。')
    source=Path(folder)/'runtime/data'
    db=source/'delivery.db'
    if not db.is_file():raise ValueError('所选目录不是旧离线包根目录（缺少 runtime/data/delivery.db）。')
    # Stage and validate before exposing the migrated database to the application.
    with tempfile.TemporaryDirectory(dir=private_dir(STORE/'tmp'),prefix='migrate-') as temporary:
        stage=Path(temporary)/'delivery.db'
        with sqlite3.connect(f'{db.resolve().as_uri()}?mode=ro',uri=True) as src,sqlite3.connect(stage) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA quick_check').fetchone()[0]!='ok':raise ValueError('旧业务库完整性校验失败。')
            from app.delivery_schema import SCHEMA_VERSION
            if dst.execute('PRAGMA user_version').fetchone()[0]>SCHEMA_VERSION:raise ValueError('旧业务库来自更新版本，不能降级导入。')
        key=source/'private/deepseek-config.json'
        model=None
        if key.is_file() and not key.is_symlink():
            from app.ai.schemas import AISettings
            model=json.loads(key.read_text())
            AISettings.model_validate(model['settings'])
            model['settings']['enabled']=False
        private_dir(STORE/'data')
        if model:save_json(STORE/'data/private/deepseek-config.json',model)
        stage.chmod(0o600);stage.replace(STORE/'data/delivery.db')
    print('已导入旧离线包业务库及模型配置；AI 暂停，请核对后自行启用。微信采集请重新配置，旧目录保留。')



def diagnostic():
    # Deliberately excludes paths, account IDs, chat contents, keys and raw exception messages.
    cfg=settings()
    payload={'build':BUILD,'macos':platform.mac_ver()[0],'architecture':platform.machine(),
             'python':platform.python_version(),'collection_configured':bool(cfg.get('collection')),
             'managed_service_running':owned_process(process_record()),'wechat_version':list(wechat_version()) if APP.exists() else None}
    compatibility = read_json(STORE/'support/compatibility.json', {})
    payload['compatibility'] = {key: compatibility[key] for key in ('stage','status','updated_at','databases_checked','message_tables_checked') if key in compatibility}
    path=private_dir(STORE/'support')/'diagnostic.json';save_json(path,payload)
    print('脱敏诊断已生成，不含账号路径、聊天或密钥。');return path


def menu():
    while True:
        print('\n交付小助手 · Mac\n1 环境检查\n2 首次配置 / 切换导入模式\n3 启动并打开工作台\n4 停止服务\n5 生成今日测试样例\n6 备份数据\n7 恢复备份\n8 修改端口\n9 导入旧离线包数据\n10 导出脱敏诊断\n11 打开使用手册\n0 退出菜单（后台服务继续运行）')
        choice=ask('请选择：')
        try:
            if choice=='0': return
            if choice=='1':check_environment()
            elif choice=='2':initial_setup()
            elif choice=='3':start_service()
            elif choice=='4':stop_service()
            elif choice=='5':subprocess.run(['/usr/bin/open',str(sample_files())])
            elif choice=='6':subprocess.run(['/usr/bin/open','-R',str(backup_state())])
            elif choice=='7':
                path=choose_path('选择本工具备份 ZIP')
                confirm('恢复将替换当前数据，当前数据会先自动备份。')
                restore_state(path)
            elif choice=='8':
                require_stopped();cfg=settings();cfg['port']=int(ask('输入端口（例如 8794）：'))
                if cfg['port'] in (5173,8000) or not 1024<=cfg['port']<=65535:raise ValueError('端口不符合要求。')
                save_json(STORE/'config/settings.json',cfg);print('端口已保存。')
            elif choice=='9':
                confirm('请先停止旧离线包服务。此操作复制旧数据，不修改原目录。')
                migrate_legacy(choose_path('选择旧离线包解压目录',folder=True))
            elif choice=='10':subprocess.run(['/usr/bin/open','-R',str(diagnostic())])
            elif choice=='11':subprocess.run(['/usr/bin/open',str(ROOT/'manual.html')])
            else:print('请选择菜单中的编号。')
        except (ValueError,OSError,sqlite3.Error,subprocess.SubprocessError) as exc:
            print(f'[未完成] {exc}')


def main():
    os.umask(0o077)
    parser=argparse.ArgumentParser();parser.add_argument('action',nargs='?',default='menu',choices=['menu','check','start','stop','samples','backup','restore','diagnose'])
    parser.add_argument('--no-open',action='store_true');parser.add_argument('--backup',type=Path)
    args=parser.parse_args()
    private_dir(STORE)
    with (STORE/'.manager.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise ValueError('另一个工具菜单正在运行，请先关闭它。')
        if args.action=='menu':menu()
        elif args.action=='check':check_environment()
        elif args.action=='start':start_service(not args.no_open)
        elif args.action=='stop':stop_service()
        elif args.action=='samples':print(sample_files())
        elif args.action=='backup':print(backup_state())
        elif args.action=='restore':
            if not args.backup:parser.error('restore 需要 --backup')
            restore_state(args.backup)
        elif args.action=='diagnose':print(diagnostic())

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,sqlite3.Error,subprocess.SubprocessError) as exc:
        print(f'[未完成] {exc}',file=sys.stderr);sys.exit(1)
    except (KeyboardInterrupt,EOFError):
        print('\n菜单已退出；后台服务状态不变。')
