from __future__ import annotations

import os
import tempfile
import unittest

from ai_usage_widget.lock import FileLock, LockAlreadyHeld


class TestFileLock(unittest.TestCase):
    def test_file_lock_rejects_second_owner_until_released(self) -> None:
        fd, path = tempfile.mkstemp(suffix=".lock")
        os.close(fd)
        os.remove(path)
        try:
            first = FileLock(path)
            first.acquire()
            second = FileLock(path)
            with self.assertRaises(LockAlreadyHeld):
                second.acquire()
            first.release()

            second.acquire()
            second.release()
        finally:
            if os.path.exists(path):
                os.remove(path)


if __name__ == "__main__":
    unittest.main()
