"""Integrity check against the shipped manifest; distribution SHA is verified separately."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import stat


def verify(root):
    def reject_link(path):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('Package links or reparse points are not supported')
    def walk(directory):
        for path in directory.iterdir():
            reject_link(path)
            yield path
            if path.is_dir():
                yield from walk(path)
    for path in (root, *root.parents):
        reject_link(path)
    paths = list(walk(root))
    manifest = json.loads((root/'package-manifest.json').read_text(encoding='utf-8'))
    files = manifest['files']
    for name, expected in files.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or '..' in relative.parts or '\\' in name or ':' in name:
            raise ValueError('Invalid manifest path')
        path = root.joinpath(*relative.parts)
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Package integrity check failed: '+name)
    for path in paths:
        if path.is_symlink():
            raise ValueError('Package links are not supported')
        if path.is_file() and path.relative_to(root).as_posix() not in files and path.name != 'package-manifest.json':
            raise ValueError('Unexpected package file: '+path.relative_to(root).as_posix())
    return len(files)

if __name__ == '__main__':
    try:
        print('Package integrity OK:',verify(Path(__file__).resolve().parents[1]),'files')
    except (OSError,ValueError,KeyError) as exc:
        print(str(exc),file=sys.stderr)
        sys.exit(1)
