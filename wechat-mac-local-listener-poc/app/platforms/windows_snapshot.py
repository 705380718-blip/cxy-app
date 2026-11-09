from __future__ import annotations

import shutil
import struct
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


WAL_HEADER_SIZE = 32
WAL_FRAME_HEADER_SIZE = 24
WAL_MAGIC_LITTLE_CHECKSUM = 0x377F0682
WAL_MAGIC_BIG_CHECKSUM = 0x377F0683


@dataclass(frozen=True)
class FileSignature:
    size: int
    mtime_ns: int
    device: int
    file_id: int


@dataclass(frozen=True)
class SnapshotBundle:
    directory: Path
    database: Path
    wal: Path | None
    shm: Path | None


def file_signature(path: Path) -> FileSignature:
    stat = path.stat()
    return FileSignature(stat.st_size, stat.st_mtime_ns, stat.st_dev, stat.st_ino)


def snapshot_signatures(source_db: Path) -> dict[str, FileSignature]:
    result: dict[str, FileSignature] = {}
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{source_db}{suffix}")
        if path.exists():
            result[path.name] = file_signature(path)
    return result


def capture_stable_snapshot(
    source_db: Path,
    private_root: Path,
    *,
    attempts: int = 5,
    debounce_seconds: float = 0.03,
) -> SnapshotBundle:
    if attempts < 1:
        raise ValueError("snapshot attempts must be positive")
    private_root.mkdir(parents=True, exist_ok=True)
    last_error = "source changed during snapshot"
    for _ in range(attempts):
        before = snapshot_signatures(source_db)
        if source_db.name not in before:
            raise FileNotFoundError(source_db)
        required_bytes = sum(item.size for item in before.values())
        if shutil.disk_usage(private_root).free < required_bytes * 2 + 16 * 1024 * 1024:
            raise RuntimeError("insufficient private snapshot disk space")
        directory = Path(tempfile.mkdtemp(prefix="capture-", dir=private_root))
        stable = False
        try:
            for name in before:
                shutil.copy2(source_db.parent / name, directory / name)
            if debounce_seconds:
                time.sleep(debounce_seconds)
            after = snapshot_signatures(source_db)
            if before == after:
                stable = True
                return SnapshotBundle(
                    directory=directory,
                    database=directory / source_db.name,
                    wal=(directory / f"{source_db.name}-wal")
                    if f"{source_db.name}-wal" in before
                    else None,
                    shm=(directory / f"{source_db.name}-shm")
                    if f"{source_db.name}-shm" in before
                    else None,
                )
            last_error = "DB/WAL/SHM set changed during snapshot"
        finally:
            if directory.exists() and not stable:
                shutil.rmtree(directory, ignore_errors=True)
    raise RuntimeError(last_error)


def wal_checksum(data: bytes, byte_order: str, seed: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    if len(data) % 8:
        raise ValueError("WAL checksum input must be a multiple of 8 bytes")
    prefix = ">" if byte_order == "big" else "<"
    words = struct.unpack(f"{prefix}{len(data) // 4}I", data)
    s0, s1 = seed
    for index in range(0, len(words), 2):
        s0 = (s0 + words[index] + s1) & 0xFFFFFFFF
        s1 = (s1 + words[index + 1] + s0) & 0xFFFFFFFF
    return s0, s1


def committed_wal_frames(wal_path: Path, expected_page_size: int) -> tuple[list[tuple[int, bytes]], int | None]:
    if not wal_path.exists() or wal_path.stat().st_size < WAL_HEADER_SIZE:
        return [], None
    data = wal_path.read_bytes()
    magic = struct.unpack(">I", data[:4])[0]
    if magic not in {WAL_MAGIC_LITTLE_CHECKSUM, WAL_MAGIC_BIG_CHECKSUM}:
        raise RuntimeError("invalid WAL magic")
    byte_order = "little" if magic == WAL_MAGIC_LITTLE_CHECKSUM else "big"
    version = struct.unpack(">I", data[4:8])[0]
    if version != 3_007_000:
        raise RuntimeError("unsupported WAL format version")
    page_size = struct.unpack(">I", data[8:12])[0]
    if page_size == 1:
        page_size = 65536
    if page_size != expected_page_size:
        raise RuntimeError("WAL page size does not match decoder profile")
    checksum = wal_checksum(data[:24], byte_order)
    stored_header = struct.unpack(">II", data[24:32])
    if checksum != stored_header:
        raise RuntimeError("WAL header checksum mismatch")
    salt = data[16:24]
    frame_size = WAL_FRAME_HEADER_SIZE + page_size
    complete_count = max(0, (len(data) - WAL_HEADER_SIZE) // frame_size)
    valid: list[tuple[int, bytes, int]] = []
    for index in range(complete_count):
        offset = WAL_HEADER_SIZE + index * frame_size
        header = data[offset : offset + WAL_FRAME_HEADER_SIZE]
        page = data[offset + WAL_FRAME_HEADER_SIZE : offset + frame_size]
        page_number, database_size = struct.unpack(">II", header[:8])
        if page_number <= 0 or header[8:16] != salt:
            break
        checksum = wal_checksum(header[:8] + page, byte_order, checksum)
        if checksum != struct.unpack(">II", header[16:24]):
            break
        valid.append((page_number, page, database_size))
    last_commit = -1
    committed_size: int | None = None
    for index, (_, _, database_size) in enumerate(valid):
        if database_size:
            last_commit = index
            committed_size = database_size
    if last_commit < 0:
        return [], None
    return [(page, content) for page, content, _ in valid[: last_commit + 1]], committed_size
