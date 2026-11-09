"""Non-secret launcher configuration. No imports that initialize a database."""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.config import Settings


def describe():
    settings = Settings.from_env()
    if settings.runtime_platform != 'windows':
        raise ValueError('Windows launcher requires WML_PLATFORM=windows')
    state = Settings._windows_app_data(Path.home()).resolve()
    # Prevent state cleanup/permission management from straying outside the app directory.
    for path in (settings.database_path, settings.windows_key_store_path, settings.windows_snapshot_root):
        if path is None or state not in path.resolve().parents:
            raise ValueError('Windows writable paths must stay inside the application state directory')
    return {'port':settings.port,'host':settings.host,'state_root':str(state),
            'database_path':str(settings.database_path),
            'bootstrap_path':str(settings.database_path.parent/'private/session/open-session.html')}


if __name__ == '__main__':
    try:
        print(json.dumps(describe(),ensure_ascii=True))
    except Exception:
        print('Windows runtime configuration is invalid; check the private runtime.env file.',file=sys.stderr)
        raise SystemExit(1)
