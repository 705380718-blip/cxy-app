import importlib.util
import json
import hashlib
import os
from pathlib import Path
import plistlib
import sqlite3
import struct
import zipfile

import pytest
from Crypto.Cipher import AES

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('recipient_test',ROOT/'packaging/mac-recipient/recipient.py')
r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)

@pytest.fixture
def store(tmp_path,monkeypatch):
    root=tmp_path.resolve()/'managed';root.mkdir()
    monkeypatch.setattr(r,'STORE',root)
    return root


def encrypted_db(path,key):
    page=bytearray(4096);page[16:18]=struct.pack('>H',4096)
    page[18:24]=bytes([1,1,80,64,32,32]);iv=b'i'*16
    page[16:4016]=AES.new(key,AES.MODE_CBC,iv).encrypt(bytes(page[16:4016]));page[4016:4032]=iv
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(page)


def test_all_shards_required_and_revalidated(tmp_path):
    db=tmp_path/'db';key=b'k'*32
    encrypted_db(db/'contact/contact.db',key);encrypted_db(db/'message/message_0.db',key)
    keys={'contact':key.hex(),'message_0':key.hex()}
    assert len(r.validate_keys(db,keys))==2
    encrypted_db(db/'message/message_1.db',key)
    with pytest.raises(ValueError,match='验证失败'):r.validate_keys(db,keys)
    with pytest.raises(ValueError):r.validate_keys(db,{'contact':'wrong'})


def test_no_messages_not_success(tmp_path):
    encrypted_db(tmp_path/'contact/contact.db',b'k'*32)
    with pytest.raises(ValueError,match='缺少'):r.required_databases(tmp_path)


@pytest.mark.parametrize('version,build,allowed',[('4.1.13','269629',True),('4.1.13','999999',False),('4.0.0','1',False),('4.2.0','1',False)])
def test_exact_version_gate(tmp_path,version,build,allowed):
    app=tmp_path/'WeChat.app';(app/'Contents').mkdir(parents=True)
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':version,'CFBundleVersion':build}))
    if allowed:assert r.require_supported(app)==(version,build)
    else:
        with pytest.raises(ValueError,match='不在已登记兼容范围'):r.require_supported(app)


def test_default_profile_has_no_collection_or_cloud_keys(store,monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY','fixture-secret')
    monkeypatch.setenv('WML_DECODER_COMMAND','["bad"]')
    envfile,port=r.write_env(r.settings())
    assert 'WML_DECODER_COMMAND=[]' in envfile.read_text()
    assert 'fixture-secret' not in envfile.read_text()
    assert not any(k.startswith(('WML_','DEEPSEEK_')) for k in r.child_env())
    assert port==8792 and envfile.stat().st_mode&0o777==0o600


@pytest.mark.parametrize('port',[5173,8000,80,65536])
def test_reserved_port_rejected(store,port):
    with pytest.raises(ValueError):r.write_env({'port':port,'collection':False})


def test_backup_restore_preserves_committed_wal_and_credentials(store):
    data=r.private_dir(store/'data');db=data/'delivery.db'
    conn=sqlite3.connect(db);conn.execute('PRAGMA journal_mode=WAL');conn.execute('CREATE TABLE items(value)');conn.execute('INSERT INTO items VALUES(1)');conn.commit()
    r.save_json(store/'config/settings.json',{'port':8795,'collection':False})
    r.save_json(data/'private/deepseek-config.json',{'api_key':'fixture-not-real'})
    backup=r.backup_state();conn.close()
    with sqlite3.connect(db) as conn:conn.execute('UPDATE items SET value=2')
    r.restore_state(backup)
    with sqlite3.connect(db) as conn:assert conn.execute('SELECT value FROM items').fetchone()[0]==1
    assert r.read_json(data/'private/deepseek-config.json')['api_key']=='fixture-not-real'
    assert backup.stat().st_mode&0o777==0o600
    assert len(list((store/'backups').glob('*.zip')))==2


@pytest.mark.parametrize('name',['../escape','/escape','config/../../escape','data\\escape','code.py'])
def test_unsafe_restore_rejected_before_mutation(store,tmp_path,name):
    r.save_json(store/'config/settings.json',{'preserve':True})
    package=tmp_path/'bad.zip'
    with zipfile.ZipFile(package,'w') as z:z.writestr(name,'bad')
    with pytest.raises((ValueError,KeyError)):r.restore_state(package)
    assert r.read_json(store/'config/settings.json')=={'preserve':True}


def test_bad_hash_and_future_build_rejected(store,tmp_path):
    for build,digest in [('future',hashlib.sha256(b'{}').hexdigest()),(r.BUILD,'bad')]:
        path=tmp_path/'bad.zip'
        with zipfile.ZipFile(path,'w') as z:
            z.writestr('config/settings.json','{}');z.writestr('backup-manifest.json',json.dumps({'format':1,'build':build,'files':{'config/settings.json':digest}}))
        with pytest.raises(ValueError):r.restore_state(path)


def test_restore_rolls_back_on_replace_error(store,tmp_path,monkeypatch):
    r.save_json(store/'config/settings.json',{'state':'before'})
    r.private_dir(store/'data')
    with sqlite3.connect(store/'data/delivery.db') as c:c.execute('CREATE TABLE sample(value)')
    backup=r.backup_state()
    r.save_json(store/'config/settings.json',{'state':'current'})
    original=Path.rename
    def fail_data(self,target):
        if self.name=='data' and self.parent.name.startswith('restore-'):raise OSError('fixture interrupted restore')
        return original(self,target)
    monkeypatch.setattr(Path,'rename',fail_data)
    with pytest.raises(OSError):r.restore_state(backup)
    assert r.read_json(store/'config/settings.json')['state']=='current'
    assert (store/'data/delivery.db').exists()


def test_stop_never_kills_unrelated_process(store,monkeypatch):
    r.save_json(store/'service.json',{'pid':os.getpid(),'port':8792,'command':'unrelated','run_path':'bad'})
    monkeypatch.setattr(r.os,'kill',lambda *a:pytest.fail('must not kill'))
    r.stop_service()


def test_symlink_data_path_rejected(store,tmp_path):
    (store/'data').symlink_to(tmp_path,target_is_directory=True)
    with pytest.raises(ValueError,match='链接'):r.write_env(r.settings())


def test_samples_use_today_and_diagnostics_exclude_secrets(store):
    path=r.sample_files();assert r.datetime.now(r.timezone(r.timedelta(hours=8))).strftime('%Y-%m-%d') in (path/'sample-chat.txt').read_text()
    r.save_json(store/'config/settings.json',{'collection':True,'db_base':'fixture-private-account','key':'fixture-secret'})
    content=r.diagnostic().read_text()
    assert 'fixture-secret' not in content and 'fixture-private-account' not in content and str(store) not in content


def test_migration_preserves_source_and_rejects_overwrite(store,tmp_path):
    old=tmp_path/'old';db=old/'runtime/data/delivery.db';db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as c:c.execute('CREATE TABLE records(id)');c.execute('INSERT INTO records VALUES(7)')
    digest=hashlib.sha256(db.read_bytes()).hexdigest()
    r.migrate_legacy(old)
    assert hashlib.sha256(db.read_bytes()).hexdigest()==digest
    with sqlite3.connect(store/'data/delivery.db') as c:assert c.execute('SELECT id FROM records').fetchone()[0]==7
    with pytest.raises(ValueError,match='不能直接覆盖'):r.migrate_legacy(old)


def test_newer_schema_migration_leaves_no_partial_database(store,tmp_path):
    old=tmp_path/'newer';db=old/'runtime/data/delivery.db';db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as c:c.execute('PRAGMA user_version=9999')
    with pytest.raises(ValueError,match='不能降级'):r.migrate_legacy(old)
    assert not (store/'data/delivery.db').exists()


def test_migration_preserves_key_but_pauses_ai(store,tmp_path):
    from app.ai.schemas import AISettings
    old=tmp_path/'old';db=old/'runtime/data/delivery.db';db.parent.mkdir(parents=True)
    with sqlite3.connect(db) as c:c.execute('CREATE TABLE fixture(value)')
    key=db.parent/'private/deepseek-config.json';key.parent.mkdir()
    key.write_text(json.dumps({'settings':AISettings(enabled=True).model_dump(),'api_key':'fixture-key'}))
    r.migrate_legacy(old)
    model=r.read_json(store/'data/private/deepseek-config.json')
    assert model['api_key']=='fixture-key' and model['settings']['enabled'] is False
    assert json.loads(key.read_text())['settings']['enabled'] is True


def test_capture_failure_is_actionable_and_cleans_owned_process(tmp_path,monkeypatch):
    import types
    import sys
    s=importlib.util.spec_from_file_location('capture_test',ROOT/'packaging/mac-recipient/mac_key_setup.py')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
    db=tmp_path/'fixture.db';encrypted_db(db,b'k'*32)
    killed=[]
    class Device:
        def spawn(self,args):return 4321
        def attach(self,pid):raise RuntimeError('fixture-private-error-detail')
        def kill(self,pid):killed.append(pid)
    monkeypatch.setitem(sys.modules,'frida',types.SimpleNamespace(get_local_device=lambda:Device()))
    with pytest.raises(ValueError,match='首次准备未完成') as error:m.collect_keys(tmp_path/'owned-fixture',[db],timeout=1)
    assert 'fixture-private-error-detail' not in str(error.value)
    assert killed==[4321]


def make_candidate_app(tmp_path, build='270115'):
    app=tmp_path/'WeChat.app';(app/'Contents').mkdir(parents=True,exist_ok=True)
    (app/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleShortVersionString':'4.1.15','CFBundleVersion':build}))
    return app


def test_415_exact_candidate_can_enter_validation_but_other_build_cannot(tmp_path):
    app=make_candidate_app(tmp_path)
    assert r.require_supported(app)==('4.1.15','270115')
    make_candidate_app(tmp_path,'270116')
    with pytest.raises(ValueError):r.require_supported(app)


def test_415_cannot_enable_by_only_changing_version_maximum(store,tmp_path):
    app=make_candidate_app(tmp_path);db=tmp_path/'db';key=b'k'*32
    encrypted_db(db/'contact/contact.db',key);encrypted_db(db/'message/message_0.db',key)
    keys={'contact':key.hex(),'message_0':key.hex()}
    r.save_json(store/'config/wechat-keys.json',keys)
    cfg={'collection':True,'wechat_app':str(app),'wechat_version':['4.1.15','270115'],'db_base':str(db)}
    with pytest.raises(ValueError,match='必须先完成'):r.write_env(cfg)
    canonical=r.validate_keys(db,keys)
    cfg['local_validation']={'profile':r.COMPATIBILITY_PROFILE,'status':'database-validated',
                             'binding':r.compatibility_binding('4.1.15','270115',db,canonical)}
    r.save_json(store/'config/settings.json',cfg)
    envfile,_=r.write_env(cfg)
    assert 'WML_MAX_VERIFIED_WECHAT_VERSION=4.1.15' in envfile.read_text()
    assert 'WML_ALLOW_UNVERIFIED_DECODER=false' in envfile.read_text()
    assert '--validation-config' in envfile.read_text()
    cfg['local_validation']['binding']='stale'
    with pytest.raises(ValueError,match='必须先完成'):r.verify_collection(cfg)


def plaintext_fixture(path, sql):
    """Use SQLite reserve bytes to produce a real SQLCipher-shaped fixture, not fake pages."""
    import ctypes,ctypes.util
    lib=ctypes.CDLL(ctypes.util.find_library('sqlite3'))
    lib.sqlite3_open.argtypes=[ctypes.c_char_p,ctypes.POINTER(ctypes.c_void_p)]
    lib.sqlite3_file_control.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_int,ctypes.c_void_p]
    lib.sqlite3_exec.argtypes=[ctypes.c_void_p,ctypes.c_char_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p]
    lib.sqlite3_close.argtypes=[ctypes.c_void_p]
    path.parent.mkdir(parents=True,exist_ok=True);handle=ctypes.c_void_p()
    assert lib.sqlite3_open(str(path).encode(),ctypes.byref(handle))==0
    try:
        reserve=ctypes.c_int(80)
        assert lib.sqlite3_file_control(handle,None,38,ctypes.byref(reserve))==0
        assert lib.sqlite3_exec(handle,('PRAGMA page_size=4096; VACUUM;'+sql).encode(),None,None,None)==0
    finally:lib.sqlite3_close(handle)
    assert path.read_bytes()[20]==80


def make_encrypted_schema_fixture(tmp_path, *, bad_columns=False, corrupt=False):
    import hashlib
    key=b'k'*32;db=tmp_path/'db_storage';keys={}
    message_columns='local_id INTEGER, server_id INTEGER, local_type INTEGER, real_sender_id INTEGER, create_time INTEGER, message_content BLOB'
    if not bad_columns:message_columns+=', compress_content BLOB'
    group_id='fixture@chatroom';table='Msg_'+hashlib.md5(group_id.encode()).hexdigest()
    statements={
        'contact/contact.db':"CREATE TABLE contact(username TEXT,nick_name TEXT,remark TEXT,alias TEXT); INSERT INTO contact VALUES('fixture@chatroom','构造测试群','','');",
        'message/message_0.db':f'CREATE TABLE Name2Id(user_name TEXT); CREATE TABLE [{table}]({message_columns});'
    }
    if not bad_columns:
        statements['message/message_0.db']+=f"INSERT INTO [{table}] VALUES(1,22,1,2,1900000000,'构造编号 WX415-001',NULL);"
    for relative,sql in statements.items():
        plain=tmp_path/'plain'/relative;plaintext_fixture(plain,sql)
        payload=plain.read_bytes();encrypted=bytearray()
        for i in range(0,len(payload),4096):
            page=bytearray(4096);start=16 if i==0 else 0;iv=b'i'*16
            if i==0:page[:16]=b's'*16
            page[start:4016]=AES.new(key,AES.MODE_CBC,iv).encrypt(payload[i+start:i+4016]);page[4016:4032]=iv
            encrypted.extend(page)
        if corrupt and relative.startswith('message'):encrypted[4096:4112]=bytes(16)
        dest=db/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(encrypted);keys[relative]=key.hex()
    return db,keys


def test_415_real_encrypted_fixture_validates_and_decodes(store,tmp_path):
    from scripts.local_vault_decoder import decrypt_snapshot, read_messages
    db,keys=make_encrypted_schema_fixture(tmp_path)
    keys=r.validate_keys(db,keys)
    summary=r.validate_local_databases(db,keys)
    assert summary=={'databases_checked':2,'message_tables_checked':1}
    for path in r.required_databases(db):
        relative=path.relative_to(db);decrypt_snapshot(path,store/'vault'/relative,keys[relative.as_posix()])
    messages=read_messages(store/'vault','构造测试群',None)
    assert len(messages)==1 and messages[0]['content']=='构造编号 WX415-001'
    assert messages[0]['source_id']==read_messages(store/'vault','构造测试群',None)[0]['source_id']


@pytest.mark.parametrize('bad_columns,corrupt',[(True,False),(False,True)])
def test_415_schema_or_integrity_failure_does_not_enable(store,tmp_path,bad_columns,corrupt):
    db,keys=make_encrypted_schema_fixture(tmp_path,bad_columns=bad_columns,corrupt=corrupt)
    with pytest.raises(ValueError,match='未启用采集'):r.validate_local_databases(db,keys)
    assert r.settings()['collection'] is False
    assert list((store/'tmp').iterdir())==[]


def test_415_receipt_bound_to_account_and_exact_keys(tmp_path):
    db=tmp_path/'db';keys={'contact/contact.db':('01'*32)}
    cfg={'wechat_version':['4.1.15','270115'],'local_validation':{
        'profile':r.COMPATIBILITY_PROFILE,'status':'database-validated',
        'binding':r.compatibility_binding('4.1.15','270115',db,keys)}}
    r.require_local_validation(cfg,db,keys)
    for actual_db,actual_keys in [(tmp_path/'other',keys),(db,{'contact/contact.db':('02'*32)})]:
        with pytest.raises(ValueError):r.require_local_validation(cfg,actual_db,actual_keys)


def test_compatibility_diagnostics_record_stage_without_private_data(store):
    r.compatibility_status('database-validation',wechat_version=['4.1.15','270115'],account='secret-account',key='secret-key')
    r.compatibility_status('database-validation','failed')
    report=json.loads(r.diagnostic().read_text())
    assert report['compatibility']['stage']=='database-validation'
    assert report['compatibility']['status']=='failed'
    assert 'secret-' not in json.dumps(report)


def test_new_release_can_restore_november_fifth_backup(store,tmp_path):
    data=b'{"collection":false}'
    path=tmp_path/'old.zip'
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('config/settings.json',data)
        z.writestr('backup-manifest.json',json.dumps({'format':1,'build':'recipient-20261105','files':{'config/settings.json':hashlib.sha256(data).hexdigest()}}))
    r.restore_state(path)
    assert r.settings()['collection'] is False
