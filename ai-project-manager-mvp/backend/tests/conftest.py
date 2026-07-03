import os
import shutil
import tempfile
from pathlib import Path


TEST_ROOT = Path(tempfile.mkdtemp(prefix="ai-pm-backend-tests-"))
os.environ.setdefault("AI_PM_DB_PATH", str(TEST_ROOT / "data" / "app.db"))
os.environ.setdefault("AI_PM_STORAGE_DIR", str(TEST_ROOT / "storage"))


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(TEST_ROOT, ignore_errors=True)


def pytest_runtest_setup(item):
    from app.db import DB_PATH, STORAGE_DIR, init_db

    if DB_PATH.exists():
        DB_PATH.unlink()
    if STORAGE_DIR.exists():
        shutil.rmtree(STORAGE_DIR)
    init_db()
