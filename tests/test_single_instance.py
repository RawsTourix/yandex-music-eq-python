"""Windows named mutex and local activation of the existing instance."""
from __future__ import annotations

import os
import unittest

from PySide6.QtCore import QCoreApplication

from single_instance import (
    ActivationServer, WindowsInstanceMutex, notify_running_instance,
)


@unittest.skipUnless(os.name == "nt", "Windows mutex and named-pipe tests")
class SingleInstanceTests(unittest.TestCase):
    def test_mutex_rejects_second_instance_and_releases(self):
        first, second, third = WindowsInstanceMutex(), WindowsInstanceMutex(), WindowsInstanceMutex()
        try:
            self.assertTrue(first.acquire())
            self.assertFalse(second.acquire())
            first.release()
            self.assertTrue(third.acquire())
        finally:
            third.release()
            first.release()
            second.release()

    def test_second_launch_requests_existing_window(self):
        app = QCoreApplication.instance()
        created = app is None
        if created:
            app = QCoreApplication([])
        calls = []
        server = ActivationServer(lambda: calls.append("show"))
        try:
            server.start()
            self.assertTrue(notify_running_instance())
            for _ in range(200):
                app.processEvents()
                if calls:
                    break
            self.assertEqual(calls, ["show"])
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
