"""Windows named mutex and local activation of the existing instance."""
from __future__ import annotations

import os
import threading
import time
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
            # A second process has its own event loop/thread. Sending from this
            # test's GUI thread would block the server's event loop during the
            # synchronous waitForConnected/waitForBytesWritten calls.
            responses = []
            second = threading.Thread(target=lambda: responses.append(notify_running_instance()))
            second.start()
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline and (second.is_alive() or not calls):
                app.processEvents()
                time.sleep(.005)
            second.join(timeout=2)
            self.assertFalse(second.is_alive())
            self.assertEqual(responses, [True])
            self.assertEqual(calls, ["show"])
        finally:
            server.close()


if __name__ == "__main__":
    unittest.main()
