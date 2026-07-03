from datetime import datetime
from pathlib import Path
import shutil
import sqlite3
import tempfile
import zipfile

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.db import DB_PATH, EXPORTS_DIR, STORAGE_DIR, TEMPLATES_DIR, get_connection, init_db


router = APIRouter(tags=["system"])

BACKUP_DIR = DB_PATH.parent / "backups"
EXPORT_DIR = DB_PATH.parent / "exports"
BUSINESS_TABLES = [
    "chat_messages",
    "document_versions",
    "document_templates",
    "extractions",
    "snippets",
    "milestones",
    "demands",
    "risks",
    "tasks",
    "projects",
]


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def write_database_snapshot(target: Path) -> None:
    init_db()
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as source, sqlite3.connect(target) as destination:
        source.backup(destination)


def add_file(zip_file: zipfile.ZipFile, path: Path, arcname: str) -> None:
    if path.exists() and path.is_file():
        zip_file.write(path, arcname)


def add_directory(zip_file: zipfile.ZipFile, directory: Path, arc_prefix: str) -> None:
    if not directory.exists():
        return
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            zip_file.write(path, f"{arc_prefix}/{path.relative_to(directory)}")


def build_system_archive(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmpdir:
        db_snapshot = Path(tmpdir) / "app.db"
        write_database_snapshot(db_snapshot)
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
            add_file(zip_file, db_snapshot, "backend/data/app.db")
            add_directory(zip_file, TEMPLATES_DIR, "storage/templates")
            add_directory(zip_file, EXPORTS_DIR, "storage/exports")
            zip_file.writestr(
                "manifest.txt",
                "\n".join(
                    [
                        "AI Project Manager MVP system data export",
                        f"created_at={datetime.now().isoformat(timespec='seconds')}",
                        "database=backend/data/app.db",
                        "templates=storage/templates/",
                        "exports=storage/exports/",
                    ]
                ),
            )
    return target


def clear_directory_files(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for path in directory.iterdir():
        if path.is_file() or path.is_symlink():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)


@router.get("/system/export")
def export_system_data() -> FileResponse:
    archive = build_system_archive(EXPORT_DIR / f"system-data-{timestamp()}.zip")
    return FileResponse(archive, filename=archive.name, media_type="application/zip")


@router.get("/system/backups/{filename}")
def download_system_backup(filename: str) -> FileResponse:
    if filename != Path(filename).name or not filename.endswith(".zip"):
        raise HTTPException(status_code=404, detail="Backup not found")
    backup = BACKUP_DIR / filename
    if not backup.exists() or not backup.is_file():
        raise HTTPException(status_code=404, detail="Backup not found")
    return FileResponse(backup, filename=backup.name, media_type="application/zip")


@router.post("/system/clear")
def clear_system_data() -> dict:
    init_db()
    backup = build_system_archive(BACKUP_DIR / f"system-backup-before-clear-{timestamp()}.zip")
    try:
        with get_connection() as connection:
            connection.execute("pragma foreign_keys = on")
            for table in BUSINESS_TABLES:
                connection.execute(f"delete from {table}")
            connection.execute(
                f"delete from sqlite_sequence where name in ({','.join(['?'] * len(BUSINESS_TABLES))})",
                BUSINESS_TABLES,
            )
            connection.execute(
                """
                insert into app_meta (key, value)
                values ('defaults_seeded', 'cleared')
                on conflict(key) do update set value = excluded.value
                """
            )
            connection.commit()
        clear_directory_files(TEMPLATES_DIR)
        clear_directory_files(EXPORTS_DIR)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Clear failed, backup kept at {backup}") from exc
    return {
        "status": "cleared",
        "backup_path": str(backup),
        "backup_name": backup.name,
        "backup_url": f"/api/system/backups/{backup.name}",
    }
