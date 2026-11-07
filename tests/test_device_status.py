"""Portable tests for conservative device registration status classification."""
import unittest

from device_status import classify_device, endpoint_guid

A = "{00112233-4455-6677-8899-aabbccddeeff}"
B = "{11112233-4455-6677-8899-aabbccddeeff}"


class DeviceStatusTests(unittest.TestCase):
    def test_windows_wasapi_identifier(self):
        self.assertEqual(endpoint_guid("{0.0.0.00000000}." + A), A)
        self.assertEqual(endpoint_guid("invalid"), None)

    def test_registered_default_does_not_claim_live_dsp(self):
        s = classify_device("{0.0.0.00000000}." + A, "FiiO K5 Pro", {A})
        self.assertEqual(s.state, "registered")
        self.assertIn("не проверена", s.reason)

    def test_selected_elsewhere_is_not_default(self):
        s = classify_device("{0.0.0.00000000}." + A, "FiiO K5 Pro", {B})
        self.assertEqual(s.state, "missing")
        self.assertIn("Device Selector", s.reason)

    def test_user_cancelled_device_selector(self):
        s = classify_device("{0.0.0.00000000}." + A, "FiiO K5 Pro", set())
        self.assertEqual(s.state, "missing")

    def test_unknown_qt_id_with_registration_elsewhere(self):
        s = classify_device("unrecognized", "Speakers", {A})
        self.assertEqual(s.state, "unknown")

    def test_empty_registry_has_no_post_mix(self):
        s = classify_device("unrecognized", "Speakers", set())
        self.assertEqual(s.state, "missing")

    def test_permission_error_is_unknown(self):
        s = classify_device(A, "Speakers", None)
        self.assertEqual(s.state, "unknown")


if __name__ == "__main__":
    unittest.main()
