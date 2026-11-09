from __future__ import annotations

import json
import os
import tempfile
import threading

from pydantic import Field, SecretStr, ValidationError

from ..config import ai_defaults
from ..work_items import DeliveryError
from .schemas import AISettings


class AISettingsUpdate(AISettings):
    api_key: SecretStr | None = Field(default=None)
    clear_key: bool = False


class AISettingsStore:
    def __init__(self, database_path):
        self.path = database_path.parent / 'private' / 'deepseek-config.json'
        self.lock = threading.RLock()

    def _read(self):
        if not self.path.exists():
            return {'settings':ai_defaults(), 'api_key':''}
        try:
            raw = self.path.read_bytes()
            if os.name == 'nt':
                from ..platforms.windows_security import unprotect_current_user
                raw = unprotect_current_user(raw)
            data = json.loads(raw)
            AISettings.model_validate(data['settings'])
            return data
        except (OSError, ValueError, KeyError, ValidationError) as exc:
            raise DeliveryError('ai_config_invalid','模型私有配置无法读取，请检查权限或恢复配置',409) from exc

    def snapshot(self):
        with self.lock:
            data = self._read()
            config = AISettings.model_validate(data['settings'])
            key = data.get('api_key') or os.getenv('DEEPSEEK_API_KEY','').strip()
            return config,key

    def public(self):
        config,key = self.snapshot()
        return {**config.model_dump(), 'key_configured':bool(key)}

    def save(self, update):
        with self.lock:
            data = self._read()
            key = data.get('api_key','')
            if update.clear_key:
                key = ''
            elif update.api_key is not None:
                candidate = update.api_key.get_secret_value().strip()
                if candidate:
                    if len(candidate)>512 or any(c.isspace() for c in candidate):
                        raise DeliveryError('invalid_key','API Key 格式不合法')
                    key = candidate
            data = {'settings':AISettings.model_validate(update.model_dump(exclude={'api_key','clear_key'})).model_dump(), 'api_key':key}
            self.path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            if os.name == 'nt':
                from ..platforms.windows_security import apply_current_user_acl, protect_current_user
                apply_current_user_acl(self.path.parent)
            else:
                self.path.parent.chmod(0o700)
            raw = json.dumps(data,ensure_ascii=False).encode()
            if os.name == 'nt':
                raw = protect_current_user(raw)
            fd,tmp = tempfile.mkstemp(prefix='deepseek-',dir=self.path.parent)
            try:
                with os.fdopen(fd,'wb') as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                if os.name == 'nt':
                    apply_current_user_acl(__import__('pathlib').Path(tmp))
                os.replace(tmp,self.path)
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            return self.public()
