"""Private-storage ACL order and failure tests; native DACL verification runs on Windows."""
import os
from pathlib import Path
import sqlite3
import subprocess
from types import SimpleNamespace

import pytest

from app.db import Database
from app.platforms import windows_security as security


def test_acl_uses_fixed_script_and_literal_environment_path(tmp_path, monkeypatch):
    target = tmp_path / "name'; Write-Output unsafe; '"
    target.mkdir()
    monkeypatch.setattr(security, '_require_windows', lambda:None)
    seen = []
    def run(args, **kwargs):
        seen.append((args, kwargs))
        assert str(target) not in args[-1]
        assert kwargs['env']['WML_ACL_TARGET'] == str(target)
        assert '-NonInteractive' in args and '-NoProfile' in args
        assert kwargs.get('shell') is not True
        assert 'New-Object Security.AccessControl.DirectorySecurity' in args[-1]
        assert '$acl.SetAccessRuleProtection($true,$false)' in args[-1]
        assert '$rules.Count -ne 1' in args[-1]
        return SimpleNamespace(returncode=0, stdout='WML-ACL-OK\n')
    monkeypatch.setattr(security.subprocess, 'run', run)
    security.apply_current_user_acl(target)
    assert len(seen) == 1


@pytest.mark.parametrize('result', [SimpleNamespace(returncode=1, stdout=''), SimpleNamespace(returncode=0, stdout='')])
def test_acl_failure_or_missing_verification_is_fail_closed(tmp_path, monkeypatch, result):
    monkeypatch.setattr(security, '_require_windows', lambda:None)
    monkeypatch.setattr(security.subprocess, 'run', lambda *a,**k:result)
    with pytest.raises(RuntimeError, match='verify'):
        security.apply_current_user_acl(tmp_path)


def test_acl_link_rejected_before_command_execution(tmp_path, monkeypatch):
    target = tmp_path/'target'; target.mkdir()
    link = tmp_path/'link'; link.symlink_to(target, target_is_directory=True)
    monkeypatch.setattr(security, '_require_windows', lambda:None)
    def forbidden(*args, **kwargs):
        pytest.fail('ACL command must not follow a symlink')
    monkeypatch.setattr(security.subprocess, 'run', forbidden)
    with pytest.raises(RuntimeError, match='link'):
        security.apply_current_user_acl(link)


def store_arguments():
    return dict(profile_id='fixture', account_fingerprint='fixture', layout_fingerprint='fixture', schema_fingerprint='fixture', keys={'message.db':{'encryption_key':'11'*32,'hmac_key':'22'*32}})


def test_key_store_protects_parent_and_empty_temporary_before_writing(tmp_path):
    calls = []
    def acl(path):
        calls.append(path)
        if path.is_file():
            assert path.read_bytes() == b''
    path = tmp_path/'private'/'keys.dpapi'
    store = security.WindowsKeyStore(path, protect=lambda raw:b'fixture-sealed', acl=acl)
    store.save(**store_arguments())
    assert calls[0] == path.parent
    assert calls[1].name.startswith('keys-')
    assert path.read_bytes() == security.DPAPI_HEADER+b'fixture-sealed'


def test_key_store_acl_failure_preserves_previous_key_and_no_temp(tmp_path):
    path = tmp_path/'keys.dpapi'; path.write_bytes(b'previous-fixture')
    def acl(target):
        if target.is_file():
            raise RuntimeError('fixture ACL failed')
    store = security.WindowsKeyStore(path, protect=lambda raw:b'fixture-sealed', acl=acl)
    with pytest.raises(RuntimeError, match='ACL failed'):
        store.save(**store_arguments())
    assert path.read_bytes() == b'previous-fixture'
    assert list(tmp_path.glob('keys-*.tmp')) == []


def test_windows_database_protects_directory_before_creation_and_backup(tmp_path, monkeypatch):
    import app.db as module
    monkeypatch.setattr(module, 'WINDOWS', True)
    path = tmp_path/'private-data'/'fixture.db'
    calls = []
    def acl(target):
        calls.append(target)
        if target.suffix == '.db' and target.parent.name == 'backups':
            assert target.stat().st_size == 0  # ACL must precede SQLite backup data.
    monkeypatch.setattr(module, 'apply_current_user_acl', acl)
    db = Database(path); db.initialize()
    assert calls[0] == path.parent and calls[-1] == path
    with sqlite3.connect(path) as conn:
        conn.execute('PRAGMA user_version=0')
    calls.clear(); db.initialize()
    backups = list((path.parent/'backups').glob('*.db'))
    assert len(backups) == 1 and backups[0].stat().st_size > 0
    assert calls.index(backups[0].parent) < calls.index(backups[0])


def test_windows_database_rejects_links_and_acl_failure_before_write(tmp_path, monkeypatch):
    import app.db as module
    monkeypatch.setattr(module, 'WINDOWS', True)
    outside = tmp_path/'outside'; outside.mkdir()
    linked = tmp_path/'linked'; linked.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match='link'):
        Database(linked/'fixture.db')
    def fail(path):
        raise RuntimeError('fixture ACL failed')
    monkeypatch.setattr(module, 'apply_current_user_acl', fail)
    path = tmp_path/'private'/'fixture.db'
    with pytest.raises(RuntimeError, match='ACL failed'):
        Database(path).initialize()
    assert not path.exists()


@pytest.mark.skipif(os.name != 'nt', reason='requires actual Windows DACL and current SID')
def test_native_acl_removes_explicit_everyone_grant(tmp_path):
    directory = tmp_path/'acl-fixture'; directory.mkdir()
    path = directory/'fixture.txt'; path.write_text('constructed data only')
    subprocess.run(['icacls', str(directory), '/grant', '*S-1-1-0:(OI)(CI)F'], check=True, capture_output=True)
    subprocess.run(['icacls', str(path), '/grant', '*S-1-1-0:F'], check=True, capture_output=True)
    # The implementation verifies protected owner-only DACL, including exact ACE count.
    security.apply_current_user_acl(directory)
    security.apply_current_user_acl(path)
