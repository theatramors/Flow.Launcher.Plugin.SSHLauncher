# -*- coding: utf-8 -*-
"""set_clipboard must not leak the GlobalAlloc block.

The clipboard owns the HGLOBAL only once SetClipboardData succeeds; on every
other path the allocation is ours and has to be GlobalFree'd.  The Win32 API is
faked, so this runs on Linux and Windows and never touches a real clipboard.
"""

from __future__ import annotations

import ctypes
import os
import sys
import types
import unittest
from unittest import mock

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

from ssh_launcher import launcher  # noqa: E402

HANDLE = 0x1000
LOCKED_POINTER = 0x2000


class FakeWin32:
    def __init__(self, alloc_ok=True, lock_ok=True, set_data_ok=True, open_ok=True):
        self.user32 = mock.MagicMock()
        self.kernel32 = mock.MagicMock()
        self.user32.OpenClipboard.return_value = 1 if open_ok else 0
        self.user32.SetClipboardData.return_value = 1 if set_data_ok else 0
        self.kernel32.GlobalAlloc.return_value = HANDLE if alloc_ok else 0
        self.kernel32.GlobalLock.return_value = LOCKED_POINTER if lock_ok else 0


class ClipboardOwnershipTest(unittest.TestCase):
    def _run(self, **kwargs):
        fake = FakeWin32(**kwargs)
        original = getattr(ctypes, "windll", None)
        ctypes.windll = types.SimpleNamespace(user32=fake.user32, kernel32=fake.kernel32)
        try:
            with mock.patch.object(ctypes, "memmove", return_value=None):
                result = launcher.set_clipboard("ssh demo@host")
        finally:
            if original is None:
                del ctypes.windll
            else:
                ctypes.windll = original
        return result, fake

    def test_success_hands_the_block_to_the_clipboard_without_freeing_it(self):
        result, fake = self._run()
        self.assertTrue(result)
        self.assertFalse(fake.kernel32.GlobalFree.called)

    def test_nothing_is_freed_when_the_allocation_itself_failed(self):
        result, fake = self._run(alloc_ok=False)
        self.assertFalse(result)
        self.assertFalse(fake.kernel32.GlobalFree.called)

    def test_a_failed_lock_frees_the_block(self):
        result, fake = self._run(lock_ok=False)
        self.assertFalse(result)
        fake.kernel32.GlobalFree.assert_called_once_with(HANDLE)

    def test_a_refused_setclipboarddata_frees_the_block(self):
        result, fake = self._run(set_data_ok=False)
        self.assertFalse(result)
        fake.kernel32.GlobalFree.assert_called_once_with(HANDLE)
