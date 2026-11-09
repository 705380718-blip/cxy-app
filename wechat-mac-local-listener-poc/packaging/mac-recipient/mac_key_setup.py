"""Explicit, local one-time setup for the owner's selected WeChat account.

Only the newly spawned disposable application copy is instrumented. No network
requests, credentials in logs, original application mutation, or global security
changes. The PBKDF hook is restricted to salts from the selected database files.
"""
from __future__ import annotations
import json
import os
import plistlib
import shutil
import subprocess
import threading
import time
import tempfile
from pathlib import Path

HOOK = r'''
const allowed = new Set(__SALTS__);
const seen = new Set();
function hex(buffer) { return Array.from(new Uint8Array(buffer), n => n.toString(16).padStart(2, '0')).join(''); }
let hooked = false;
function install() {
  if (hooked) return;
  let address;
  try { address = Module.getGlobalExportByName('CCKeyDerivationPBKDF'); } catch (_) { return; }
  Interceptor.attach(address, {
    onEnter(args) {
      this.accepted = false;
      if (args[0].toInt32() !== 2 || args[4].toUInt32() !== 16 || args[8].toUInt32() !== 32) return;
      try {
        this.salt = hex(args[3].readByteArray(16));
        if (!allowed.has(this.salt)) return;
        this.output = args[7]; this.accepted = true;
      } catch (_) {}
    },
    onLeave(result) {
      if (!this.accepted || result.toInt32() !== 0) return;
      try {
        const key = hex(this.output.readByteArray(32));
        const tag = this.salt + key;
        if (!seen.has(tag)) { seen.add(tag); send({kind:'candidate', salt:this.salt, key:key}); }
      } catch (_) {}
    }
  });
  hooked = true;
  send({kind:'hooked'});
}
install();
const observer = Process.attachModuleObserver({onAdded(module) { install(); }});
send({kind:'armed'});
'''


def collect_keys(executable: Path, databases: list[Path], timeout=180):
    import frida
    from tools.verify_keys import key_works
    if not databases: raise ValueError('没有待验证数据库。')
    by_salt={}
    for database in databases:
        with database.open('rb') as f:salt=f.read(16).hex()
        by_salt.setdefault(salt,[]).append(database)
    found={}; armed=threading.Event(); complete=threading.Event(); errors=[]
    device=frida.get_local_device();pid=None;session=None
    def on_message(message, data):
        if message.get('type')=='error':errors.append('hook-error');return
        payload=message.get('payload',{})
        if not isinstance(payload,dict): return
        if payload.get('kind')=='armed':armed.set();return
        if payload.get('kind')!='candidate':return
        for database in by_salt.get(payload.get('salt'),[]):
            if key_works(database,payload.get('key','')):found[database]=payload['key']
        if len(found)==len(databases):complete.set()
    try:
        pid=device.spawn([str(executable)])
        session=device.attach(pid)
        script=session.create_script(HOOK.replace('__SALTS__',json.dumps(list(by_salt))))
        script.on('message',on_message);script.load()
        if not armed.wait(8):raise ValueError('首次准备钩子未就绪；未继续启动副本。')
        device.resume(pid)
        print('请在刚打开的临时微信副本中完成登录，并打开需要监测的群。等待验证，最长三分钟。',flush=True)
        deadline=time.monotonic()+timeout;last_count=-1
        while time.monotonic()<deadline:
            if errors:raise ValueError('当前客户端不支持此准备方式。请使用已有密钥导入或联系发布者适配。')
            if len(found)!=last_count:
                print(f'已验证 {len(found)} / {len(databases)} 个数据库。',flush=True);last_count=len(found)
            if complete.wait(.3): return dict(found)
        raise ValueError('未获得全部数据库的有效密钥，未启用采集。请确认所选账号、客户端版本及登录状态后重试。')
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f'首次准备未完成（{type(exc).__name__}）。未更改官方微信；请查阅手册。') from None
    finally:
        if pid is not None:
            try:device.kill(pid)
            except Exception:pass
        if session is not None:
            try:session.detach()
            except Exception:pass


def capture_from_copy(app, db, store):
    from recipient import require_supported, required_databases, private_dir
    require_supported(app)
    if subprocess.run(['/usr/bin/pgrep','-x','WeChat'],capture_output=True).returncode==0:
        raise ValueError('官方微信仍在运行。请自行退出微信，再执行首次准备；工具不会强制结束它。')
    if shutil.disk_usage(store).free < 3_000_000_000:
        raise ValueError('首次准备需至少 3 GB 可用空间用于临时副本。')
    databases=required_databases(db)
    temp_root=private_dir(store/'tmp')
    with tempfile.TemporaryDirectory(prefix='wechat-setup-',dir=temp_root) as directory:
        copy=Path(directory)/'WeChat.app'
        print('正在创建临时副本；官方微信应用保持原样。',flush=True)
        subprocess.run(['/usr/bin/ditto',str(app),str(copy)],check=True,capture_output=True)
        # Ad-hoc signing is applied only to the fresh copy; no system policy changes.
        subprocess.run(['/usr/bin/codesign','--force','--deep','--sign','-','--options','0',
                        '--preserve-metadata=entitlements',str(copy)],check=True,capture_output=True)
        with (copy/'Contents/Info.plist').open('rb') as f:info=plistlib.load(f)
        name=info['CFBundleExecutable']
        if Path(name).name!=name:raise ValueError('客户端可执行文件路径不符合要求。')
        found=collect_keys(copy/'Contents/MacOS'/name,databases)
        return {p.relative_to(db).as_posix():key for p,key in found.items()}
