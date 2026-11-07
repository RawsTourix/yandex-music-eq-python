"""Installer safety checks - offline and cross-platform."""
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import installer

class DummyResponse(io.BytesIO):
    headers = {"Content-Length": "11"}
    def geturl(self):
        return "https://netix.dl.sourceforge.net/project/equalizerapo/file.exe"

class InstallerTests(unittest.TestCase):
    def test_architectures(self):
        self.assertTrue(installer.supported_architecture("AMD64"))
        self.assertFalse(installer.supported_architecture("ARM64"))
    def test_cache(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "file.exe"
            path.write_bytes(b"test payload")
            digest = hashlib.sha256(b"test payload").hexdigest()
            with patch.object(installer,"EXPECTED_SHA256",digest), \
                 patch.object(installer,"supported_architecture",return_value=True), \
                 patch("urllib.request.urlopen",side_effect=AssertionError("should not download")):
                self.assertEqual(installer.download_official_installer(destination=path),path)
    def test_download_and_sha(self):
        payload = b"hello world"
        digest = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as d, \
             patch.object(installer,"EXPECTED_SHA256",digest), \
             patch.object(installer,"supported_architecture",return_value=True), \
             patch("urllib.request.urlopen",return_value=DummyResponse(payload)):
            path = Path(d) / "file.exe"
            self.assertEqual(installer.download_official_installer(destination=path),path)
            self.assertEqual(path.read_bytes(),payload)
    def test_hash_mismatch_cleans_up(self):
        with tempfile.TemporaryDirectory() as d, \
             patch.object(installer,"supported_architecture",return_value=True), \
             patch("urllib.request.urlopen",return_value=DummyResponse(b"hello world")):
            path = Path(d) / "file.exe"
            with self.assertRaisesRegex(installer.InstallerError,"SHA-256"):
                installer.download_official_installer(destination=path)
            self.assertFalse(path.exists())
            self.assertFalse((Path(d) / "file.exe.part").exists())
if __name__ == "__main__":
    unittest.main()
