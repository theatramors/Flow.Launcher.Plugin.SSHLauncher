"""Exercise the exact release ZIP after extraction, outside the source tree."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--python', default=sys.executable)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='ssh-release-smoke-') as tmp:
        root = Path(tmp)
        plugin = root / 'plugin'
        settings = root / 'settings'
        settings.mkdir()
        with zipfile.ZipFile(args.archive) as archive:
            for name in archive.namelist():
                if Path(name).is_absolute() or '..' in Path(name).parts:
                    raise RuntimeError('Unsafe ZIP member: ' + name)
            archive.extractall(plugin)
        metadata = json.loads((plugin / 'plugin.json').read_text(encoding='utf-8'))
        (settings / 'destinations.json').write_text(json.dumps({
            'settings': {'include_ssh_config': False},
            'destinations': [{'alias': 'demo', 'host': 'server.example.com',
                              'user': 'demo', 'port': 2222}],
        }), encoding='utf-8')
        requests = [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': [{
                'currentPluginMetadata': {'pluginDirectory': str(plugin),
                                         'pluginSettingsDirectoryPath': str(settings),
                                         'version': metadata['Version']}}]},
            {'jsonrpc': '2.0', 'id': 2, 'method': 'query',
             'params': [{'search': 'demo', 'actionKeyword': 'ssh'}, {}]},
            {'jsonrpc': '2.0', 'id': 3, 'method': 'context_menu', 'params': ['demo']},
            {'jsonrpc': '2.0', 'id': 4, 'method': 'close', 'params': []},
        ]
        response = subprocess.run([args.python, str(plugin / metadata['ExecuteFileName'])],
                                  input=''.join(json.dumps(r) + '\n' for r in requests),
                                  text=True, capture_output=True, cwd=root, timeout=45)
        if response.returncode != 0 or response.stderr.strip():
            raise RuntimeError('Packaged entry point failed: ' + response.stderr)
        replies = [json.loads(line) for line in response.stdout.splitlines() if line.strip()]
        if len(replies) != len(requests) or any('error' in r for r in replies):
            raise RuntimeError('Invalid replies from packaged entry point')
        rows = replies[1]['result']['result']
        demo = next(r for r in rows if r['Title'] == 'demo')
        if 'demo@server.example.com' not in demo['SubTitle']:
            raise RuntimeError('Packaged query did not build the SSH destination')
        if not Path(demo['IcoPath']).is_file():
            raise RuntimeError('Packaged icon does not resolve')
        if len(replies[2]['result']['result']) < 4:
            raise RuntimeError('Packaged context menu is missing actions')
    print('Release ZIP smoke PASS: initialize, query, icon, context menu, close')


if __name__ == '__main__':
    main()
