"""Release packaging regression: no personal data or development debris."""
import importlib.util
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ReleasePackageTests(unittest.TestCase):
    def test_explicit_allowlist_and_root_manifest(self):
        tool = ROOT / 'tools' / 'package.py'
        self.assertTrue(tool.is_file(), 'A reproducible release packager is required')
        spec = importlib.util.spec_from_file_location('release_packager', tool)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix='ssh-package-test-') as tmp:
            root = pathlib.Path(tmp) / 'source'
            root.mkdir()
            # Exercise the actual declared public files in an isolated fixture.
            for name in module.RELEASE_FILES:
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((ROOT / name).read_bytes())
            for name in ('logs/ssh-launcher.log', 'destinations.json',
                         '.git/config', 'tests/secret_fixture.py',
                         'ssh_launcher/__pycache__/config.pyc',
                         'ssh_launcher/private-local.py'):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text('PRIVATE DATA MUST NOT SHIP')
            output = pathlib.Path(tmp) / 'plugin.zip'
            module.build(root, output)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), set(module.RELEASE_FILES))
                metadata = json.loads(archive.read('plugin.json'))
                self.assertEqual(metadata['Name'], 'SSH Launcher')
                self.assertEqual(metadata['Author'], 'Vadim Funtikov')
                self.assertTrue(metadata.get('MinimumAppVersion'))
                self.assertIn(metadata['ExecuteFileName'], archive.namelist())
                self.assertFalse(any(b'PRIVATE DATA MUST NOT SHIP' in archive.read(n)
                                     for n in archive.namelist()))

    def test_missing_runtime_file_aborts_without_partial_archive(self):
        tool = ROOT / 'tools' / 'package.py'
        self.assertTrue(tool.is_file(), 'A reproducible release packager is required')
        spec = importlib.util.spec_from_file_location('release_packager', tool)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory(prefix='ssh-package-missing-') as tmp:
            root = pathlib.Path(tmp) / 'source'
            root.mkdir()
            output = pathlib.Path(tmp) / 'plugin.zip'
            with self.assertRaises(FileNotFoundError):
                module.build(root, output)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
