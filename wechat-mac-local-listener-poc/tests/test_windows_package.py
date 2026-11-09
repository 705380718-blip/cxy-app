import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import zipfile
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('windows_builder',ROOT/'scripts/build-windows-package.py')
builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
from tools.export_legacy_windows import export_legacy
from tools.verify_windows_package import verify
from tools.windows_selftest import run_selftest

@pytest.mark.parametrize('name',['../escape','/absolute','C:/drive','a\\escape','a/CON.txt','a/trailing.','a/name '])
def test_archive_traversal_and_windows_aliases_rejected(tmp_path,name):
    archive=tmp_path/'fixture.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr(name,'bad')
    with pytest.raises(ValueError):builder.extract_verified(archive,tmp_path/'out')
    assert not (tmp_path/'escape').exists()


def test_archive_symlinks_and_case_collisions_rejected(tmp_path):
    archive=tmp_path/'fixture.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('one','a');z.writestr('ONE','b')
    with pytest.raises(ValueError,match='duplicate'):builder.extract_verified(archive,tmp_path/'out')
    with zipfile.ZipFile(archive,'w') as z:
        info=zipfile.ZipInfo('link');info.external_attr=0o120777<<16;z.writestr(info,'target')
    with pytest.raises(ValueError,match='symlink'):builder.extract_verified(archive,tmp_path/'other')


def fake_wheel(tmp_path, dependency=''):
    wheel=tmp_path/'fixture-1-py3-none-any.whl'
    with zipfile.ZipFile(wheel,'w') as z:z.writestr('fixture-1.dist-info/METADATA','Name: fixture\nVersion: 1\n'+dependency)
    return {'name':'fixture','version':'1','filename':wheel.name,'sha256':builder.digest(wheel)}


def test_windows_markers_are_resolved_even_when_building_on_mac(tmp_path):
    record=fake_wheel(tmp_path,'Requires-Dist: missing-win; sys_platform == "win32"\n')
    with pytest.raises(ValueError,match='unresolved Windows'):builder.validate_dependencies({'dependencies':[record]},tmp_path)
    record=fake_wheel(tmp_path,'Requires-Dist: missing-mac; sys_platform == "darwin"\n')
    assert builder.validate_dependencies({'dependencies':[record]},tmp_path)==[record]
    record['sha256']='0'*64
    with pytest.raises(ValueError,match='hash'):builder.validate_dependencies({'dependencies':[record]},tmp_path)


def test_package_tampering_and_extra_source_are_detected(tmp_path):
    path=tmp_path/'run.py';path.write_text('print(1)')
    (tmp_path/'package-manifest.json').write_text(json.dumps({'files':{'run.py':builder.digest(path)}}))
    assert verify(tmp_path)==1
    path.write_text('print(2)')
    with pytest.raises(ValueError,match='integrity'):verify(tmp_path)
    path.write_text('print(1)');(tmp_path/'extra.pth').write_text('import unexpected')
    with pytest.raises(ValueError,match='Unexpected'):verify(tmp_path)


def test_legacy_export_is_read_only_private_and_repeatable(tmp_path):
    source=tmp_path/'legacy.db'
    with sqlite3.connect(source) as db:
        db.execute('CREATE TABLE messages(id INTEGER PRIMARY KEY,source_event_id TEXT,chat_name TEXT,sender TEXT,content TEXT,source_time TEXT)')
        db.execute('INSERT INTO messages VALUES(1,?,?,?,?,?)',('external-id','../../CON','构造成员','=untrusted formula','2026-10-12T01:00:00+00:00'))
    before=hashlib.sha256(source.read_bytes()).digest()
    result=export_legacy(source,tmp_path/'export')
    assert result['messages']==1 and result['review_history_imported'] is False
    assert hashlib.sha256(source.read_bytes()).digest()==before
    entry=json.loads((tmp_path/'export/export-index.json').read_text())['groups'][0]
    assert entry['file'].startswith('group-') and '/' not in entry['file']
    with pytest.raises(FileExistsError):export_legacy(source,tmp_path/'export')
    export_legacy(source,tmp_path/'second')
    assert (tmp_path/'export'/entry['file']).read_bytes()==(tmp_path/'second'/entry['file']).read_bytes()


def test_shipped_offline_selftest_exercises_whole_pipeline(tmp_path):
    result=run_selftest(tmp_path)
    assert result['status']=='passed'
    assert result['real_model']==result['real_wechat']=='not-tested'
    assert len(result['checks'])>=5


def test_unlisted_bytecode_cannot_bypass_source_hash_check(tmp_path):
    import py_compile
    source=tmp_path/'fixture.py';source.write_text("VALUE='approved'\n")
    (tmp_path/'package-manifest.json').write_text(json.dumps({'files':{'fixture.py':builder.digest(source)}}))
    py_compile.compile(str(source),doraise=True)
    with pytest.raises(ValueError,match='Unexpected package file'):
        verify(tmp_path)


def test_snapshot_workspace_rejects_links_and_keeps_private_permissions(tmp_path, monkeypatch):
    import os
    from scripts.windows_vault_decoder import create_private_session
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    vault=tmp_path/'GroupChatOrganizer/private/snapshots'
    account=tmp_path/'separate-wechat-account';account.mkdir()
    session=create_private_session(vault,account,'decode-session-')
    assert session.parent==vault and {p.name for p in session.iterdir()}=={'decrypted','captures'}
    if os.name != 'nt':
        assert session.stat().st_mode & 0o777 == 0o700
    link=tmp_path/'redirect';link.symlink_to(vault,target_is_directory=True)
    with pytest.raises(RuntimeError,match='link'):
        create_private_session(link,account,'decode-session-')
