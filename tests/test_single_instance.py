"""Windows mutex and native event ensure one interactive-session instance."""
from __future__ import annotations

import os
import unittest

from single_instance import (
    ActivationEvent, WindowsInstanceMutex, notify_running_instance,
)


@unittest.skipUnless(os.name == "nt", "Windows-only kernel synchronization")
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

    def test_second_launch_signals_existing_instance(self):
        # Simulates two processes with independent handles to the same
        # named Windows event: no reliance on Qt event-loop timing.
        primary = ActivationEvent()
        try:
            primary.create()
            self.assertFalse(primary.consume())
            self.assertTrue(notify_running_instance())
            self.assertTrue(primary.consume())
            self.assertFalse(primary.consume())  # auto-reset semantics
        finally:
            primary.close()

    def test_closed_event_no_longer_reported_active(self):
        event = ActivationEvent()
        event.create()
        event.close()
        self.assertFalse(event.consume())


if __name__ == "__main__":
    unittest.main()
