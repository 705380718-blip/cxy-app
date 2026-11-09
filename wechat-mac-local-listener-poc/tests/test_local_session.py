"""Local sessions use constructed tokens and data; Windows ACL has a test seam."""
from dataclasses import replace
from pathlib import Path
import re
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from app.local_session import LocalSession
from app.main import create_app


def owner_only(path):
    path.chmod(0o700 if path.is_dir() else 0o600)


def bootstrap_token(session):
    return re.search(r'name="token" value="([^"]+)"', session.bootstrap_path.read_text()).group(1)


@pytest.fixture
def protected_client(settings, tmp_path):
    session = LocalSession(tmp_path/'private'/'session', settings.port, acl=owner_only)
    token = bootstrap_token(session)
    app = create_app(settings, start_analysis_worker=False, local_session=session)
    with TestClient(app, base_url=f'http://127.0.0.1:{settings.port}') as client:
        yield client, session, token


@pytest.mark.parametrize('path', ['/api/messages', '/api/projects', '/api/settings', '/api/ai/settings', '/api/docs', '/openapi.json', '/api/followup-reports/1/export', '/api/evaluations/1/export'])
def test_business_reads_docs_and_exports_require_session(protected_client, path):
    client, session, token = protected_client
    response = client.get(path)
    assert response.status_code == 401
    assert token not in response.text
    assert response.headers['cache-control'] == 'no-store'


def test_public_health_is_minimal_and_root_has_login_guidance(protected_client):
    client, _, token = protected_client
    health = client.get('/api/health').json()
    assert set(health) == {'status', 'product', 'version', 'platform', 'build', 'schema', 'instance_id', 'session_required'}
    assert health['session_required'] is True
    assert health['version'] == '0.5.7' and health['build'] == 'security-20261012'
    assert health['platform'] == 'macos'  # injected session on the shared macOS fixture
    assert '本机启动入口' in client.get('/').text
    assert token not in str(health) + client.get('/').text
    assert client.post('/api/projects', json={'name':'denied'}).status_code == 401


def test_bootstrap_exchange_once_sets_private_cookie_and_unlocks_app(protected_client):
    client, session, token = protected_client
    original_file = session.bootstrap_path.read_text()
    assert f'action="{session.origin}/api/session/exchange"' in original_file
    assert '?' not in original_file and 'localStorage' not in original_file
    response = client.post('/api/session/exchange', data={'token':token}, headers={'Origin':'null'}, follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'] == '/'
    cookie = response.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Path=/' in cookie
    assert 'Domain=' not in cookie and 'Max-Age=' not in cookie
    assert token not in response.text + cookie
    assert not session.bootstrap_path.exists()
    assert client.get('/api/projects').status_code == 200
    assert client.get('/openapi.json').status_code == 200
    assert 'workflow.js' in client.get('/').text
    assert client.post('/api/session/exchange', data={'token':token}, headers={'Origin':'null'}).status_code == 403
    assert client.post('/api/projects', json={'name':'valid session'}).status_code == 201
    # A session cookie never authorizes cross-origin mutations, including null.
    for origin in ('null', 'https://evil.invalid', 'http://127.0.0.1:9999'):
        assert client.post('/api/projects', json={'name':'denied'}, headers={'Origin':origin}).status_code == 403


def test_invalid_exchange_never_echoes_input_or_consumes_valid_token(protected_client):
    client, session, token = protected_client
    for data in ('token=bogus', 'token=one&token=two', 'token=bogus&extra=x', 'bad'):
        response = client.post('/api/session/exchange', content=data, headers={'Origin':'null', 'Content-Type':'application/x-www-form-urlencoded'})
        assert response.status_code == 403 and 'bogus' not in response.text
    assert client.post('/api/session/exchange', json={'token':token}, headers={'Origin':'null'}).status_code == 415
    assert client.post('/api/session/exchange', data={'token':token}, headers={'Origin':'https://evil.invalid'}).status_code == 403
    assert client.post('/api/session/exchange', content='token='+'x'*2000, headers={'Origin':'null', 'Content-Type':'application/x-www-form-urlencoded'}).status_code == 413
    assert client.post('/api/session/exchange', data={'token':token}, headers={'Origin':'null'}, follow_redirects=False).status_code == 303


def test_forged_cookie_and_query_token_do_not_authenticate(protected_client):
    client, session, token = protected_client
    assert client.get('/api/messages', headers={'Cookie':f'{session.cookie_name}=bogus'}).status_code == 401
    assert client.get('/api/messages', params={'token':token}).status_code == 401
    assert client.get('/api/session/exchange', params={'token':token}).status_code == 405
    assert client.get('/api/health', headers={'Host':'evil.invalid'}).status_code == 400


def test_bootstrap_expiry_and_process_restart_revoke_tokens(tmp_path):
    now = [10.0]
    directory = tmp_path/'private'/'session'
    first = LocalSession(directory, 8791, acl=owner_only, clock=lambda:now[0], bootstrap_ttl=5)
    old_bootstrap = bootstrap_token(first)
    now[0] = 15
    assert first.exchange(old_bootstrap) is None
    second = LocalSession(directory, 8791, acl=owner_only)
    second_file = second.bootstrap_path.read_bytes()
    first.close()
    assert second.bootstrap_path.read_bytes() == second_file
    assert second.exchange(old_bootstrap) is None
    cookie = second.exchange(bootstrap_token(second))
    assert second.authenticated(cookie)
    third = LocalSession(directory, 8791, acl=owner_only)
    assert not third.authenticated(cookie)
    second.close()
    assert not second.authenticated(cookie)
    third.close()


def test_concurrent_bootstrap_only_one_exchange_wins(tmp_path):
    session = LocalSession(tmp_path/'private'/'session', 8791, acl=owner_only)
    token = bootstrap_token(session)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(session.exchange, [token]*4))
    assert sum(result is not None for result in results) == 1
    assert not session.authenticated('构造非法令牌')
    assert session.exchange('构造非法令牌') is None


def test_session_path_rejects_links_and_acl_failure_before_secret_write(tmp_path):
    outside = tmp_path/'outside'; outside.mkdir()
    link = tmp_path/'linked'; link.symlink_to(outside, target_is_directory=True)
    with pytest.raises(RuntimeError, match='链接'):
        LocalSession(link/'session', 8791, acl=owner_only)
    assert list(outside.iterdir()) == []
    def fail_acl(path):
        raise RuntimeError('fixture ACL failed')
    with pytest.raises(RuntimeError, match='ACL failed'):
        LocalSession(tmp_path/'private'/'session', 8791, acl=fail_acl)
    assert not (tmp_path/'private'/'session'/'open-session.html').exists()


def test_windows_enables_session_by_default_and_mac_remains_compatible(settings, monkeypatch):
    calls = []
    def fake_acl(path):
        calls.append(path); owner_only(path)
    monkeypatch.setattr('app.local_session.apply_current_user_acl', fake_acl)
    windows = replace(settings, runtime_platform='windows')
    app = create_app(windows, start_analysis_worker=False)
    assert isinstance(app.state.local_session, LocalSession)
    assert app.state.local_session.bootstrap_path == settings.database_path.parent/'private'/'session'/'open-session.html'
    assert calls and app.state.local_session.bootstrap_path.stat().st_mode & 0o777 == 0o600
    app.state.local_session.close()
    assert create_app(settings, start_analysis_worker=False).state.local_session is None
