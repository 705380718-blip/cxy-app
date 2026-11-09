"""Single-process local browser session established by an owner-only bootstrap file."""
from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import secrets
import stat
import tempfile
import threading
import time
from typing import Callable

from .platforms.windows_security import apply_current_user_acl


def reject_link_path(path: Path) -> None:
    """Check before resolving: junctions and symlinks must never redirect secrets."""
    for entry in reversed((path, *path.parents)):
        try:
            info = entry.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise RuntimeError('会话目录包含链接或重解析点，已拒绝启动')


class LocalSession:
    def __init__(self, directory: Path, port: int, *, acl: Callable[[Path], None] | None = None,
                 clock: Callable[[], float] = time.monotonic, bootstrap_ttl: float = 300):
        if not 1 <= port <= 65535 or not 0 < bootstrap_ttl <= 600:
            raise ValueError('invalid local session settings')
        self.directory = Path(directory).absolute()
        self.bootstrap_path = self.directory / 'open-session.html'
        self.cookie_name = f'wml_session_{port}'
        self.origin = f'http://127.0.0.1:{port}'
        self._clock = clock
        self._lock = threading.Lock()
        self._bootstrap_token = secrets.token_urlsafe(32)
        self._session_token = secrets.token_urlsafe(32)
        self._expires = clock() + bootstrap_ttl
        protect = acl or apply_current_user_acl
        reject_link_path(self.bootstrap_path)
        # Restrict the containing private directory before writing any secret.
        for path in (self.directory.parent, self.directory):
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
            reject_link_path(path)
            protect(path)
        html = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="referrer" content="no-referrer"><title>打开交付小助手</title>
<body><h1>打开交付小助手</h1><p>点击进入本机工作台。此入口五分钟内有效，仅能使用一次。</p>
<form method="post" action="{self.origin}/api/session/exchange" autocomplete="off">
<input type="hidden" name="token" value="{self._bootstrap_token}">
<button type="submit">进入交付小助手</button></form>
<p>入口失效时，请停止并重新启动服务。</p></body></html>'''
        self._file_hash = hashlib.sha256(html.encode()).digest()
        fd, temporary = tempfile.mkstemp(prefix='session-', suffix='.html', dir=self.directory)
        temporary_path = Path(temporary)
        try:
            # ACL before writing: a token must not briefly inherit a broad grant.
            protect(temporary_path)
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                fd = -1
                handle.write(html)
                handle.flush()
                os.fsync(handle.fileno())
            reject_link_path(self.bootstrap_path)
            os.replace(temporary_path, self.bootstrap_path)
        finally:
            if fd != -1:
                os.close(fd)
            temporary_path.unlink(missing_ok=True)

    def authenticated(self, cookie: str | None) -> bool:
        if not cookie or len(cookie) > 256:
            return False
        return hmac.compare_digest(self._session_token.encode(), cookie.encode())

    def exchange(self, token: str) -> str | None:
        if not isinstance(token, str) or len(token) > 256:
            return None
        with self._lock:
            expected = self._bootstrap_token
            if expected is None or self._clock() >= self._expires:
                return None
            if not hmac.compare_digest(expected.encode(), token.encode()):
                return None
            self._bootstrap_token = None
            self._remove_bootstrap()
            return self._session_token

    def _remove_bootstrap(self) -> None:
        try:
            reject_link_path(self.bootstrap_path)
            if hashlib.sha256(self.bootstrap_path.read_bytes()).digest() == self._file_hash:
                self.bootstrap_path.unlink()
        except OSError:
            pass

    def close(self) -> None:
        with self._lock:
            self._bootstrap_token = None
            self._session_token = secrets.token_urlsafe(32)
            self._remove_bootstrap()
