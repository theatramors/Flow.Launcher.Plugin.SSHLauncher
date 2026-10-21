"""Build a clean Flow Launcher release ZIP with an explicit file allowlist.

Run ``python tools/package.py`` from a source checkout. No third-party packages
are required. Logs, user config, tests, VCS files and cached bytecode never ship.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

RELEASE_FILES = (
    'plugin.json',
    'main.py',
    'README.md',
    'LICENSE',
    'Images/ssh.png',
    'Images/settings.png',
    'ssh_launcher/__init__.py',
    'ssh_launcher/arguments.py',
    'ssh_launcher/config.py',
    'ssh_launcher/launcher.py',
    'ssh_launcher/logging_setup.py',
    'ssh_launcher/matcher.py',
    'ssh_launcher/plugin.py',
    'ssh_launcher/rpc.py',
)
ASSET_NAME = 'Flow.Launcher.Plugin.SSHLauncher.zip'


def build(root, output):
    root = Path(root).resolve()
    output = Path(output).resolve()
    for name in RELEASE_FILES:
        source = root / name
        if not source.is_file() or source.is_symlink():
            raise FileNotFoundError('Missing or unsafe release file: ' + name)
    metadata = json.loads((root / 'plugin.json').read_text(encoding='utf-8'))
    if not re.fullmatch(r'\d+\.\d+\.\d+', metadata['Version']):
        raise ValueError('Version must have three numeric components')
    if metadata['ExecuteFileName'] not in RELEASE_FILES:
        raise ValueError('Entry point is not packaged')
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.partial')
    try:
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            for name in RELEASE_FILES:
                # Stable timestamps and permissions make rebuilds reproducible.
                entry = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, (root / name).read_bytes())
        temporary.replace(output)
    finally:
        if temporary.exists():
            temporary.unlink()
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = build(root, args.output or root / 'dist' / ASSET_NAME)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    checksum = output.with_suffix('.zip.sha256')
    checksum.write_text(digest + '  ' + output.name + '\n', encoding='ascii')
    print(output)
    print(digest + '  ' + output.name)


if __name__ == '__main__':
    main()
