"""Create a public Windows ZIP and verify bundled runtime files."""

import argparse
from pathlib import Path
import zipfile


ROOT_FILES = (
    'iPhone虚拟定位.exe', '一键修改.exe', 'README.md', 'LICENSE',
    'COPYRIGHT.md', 'SOURCE.md',
)
ROOT_DIRS = ('docs', 'engine', 'source')
RUNTIME_FILES = (
    'engine/LocationEngine.exe',
    *(f'engine/_internal/pytun_pmd3/wintun/bin/{arch}/wintun.dll'
      for arch in ('amd64', 'arm', 'arm64', 'x86')),
)


def package(root: Path, output: Path) -> None:
    root = root.resolve()
    output = output.resolve()
    if root == output or root in output.parents:
        raise ValueError('Output ZIP must be outside the release directory')
    for name in (*ROOT_FILES, *RUNTIME_FILES):
        if not (root / name).is_file():
            raise FileNotFoundError(f'Required release file is missing: {name}')
    for name in ROOT_DIRS:
        if not (root / name).is_dir():
            raise FileNotFoundError(f'Required release directory is missing: {name}')
    for name in ('state', 'location.xml', 'locations.xml', 'locations.xml.bak'):
        if (root / name).exists():
            raise ValueError(f'Private runtime data in release directory: {name}')

    files = [root / name for name in ROOT_FILES]
    for name in ROOT_DIRS:
        files.extend(path for path in (root / name).rglob('*') if path.is_file())
    files = sorted(files, key=lambda path: path.relative_to(root).as_posix())
    for path in files:
        if path.is_symlink() or '__pycache__' in path.parts or path.suffix == '.pyc':
            raise ValueError(f'Unexpected file in release directory: {path.relative_to(root)}')

    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + '.tmp')
    try:
        with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in files:
                archive.write(path, arcname=f'{root.name}/{path.relative_to(root).as_posix()}')
        with zipfile.ZipFile(temp) as archive:
            names = set(archive.namelist())
            for name in (*ROOT_FILES, *RUNTIME_FILES):
                if f'{root.name}/{name}' not in names:
                    raise ValueError(f'Required file absent from ZIP: {name}')
            bad = archive.testzip()
            if bad:
                raise ValueError(f'Corrupt ZIP entry: {bad}')
        temp.replace(output)
    finally:
        temp.unlink(missing_ok=True)
    print(f'{output} ({len(files)} files, {output.stat().st_size} bytes)')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path, help='Clean public release directory')
    parser.add_argument('output', type=Path, help='ZIP file outside that directory')
    args = parser.parse_args()
    package(args.root, args.output)
