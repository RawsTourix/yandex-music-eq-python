"""Offline tests for official SourceForge download and failure diagnostics."""
import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
import installer

class DummyResponse(io.BytesIO):
    def __init__(self, payload: bytes, content_type="application/octet-stream", url="https://netix.dl.sourceforge.net/project/equalizerapo/file.exe"):
        super().__init__(payload)
        self.headers={"Content-Length":str(len(payload)),"Content-Type":content_type}
        self.url=url
    def geturl(self):
        return self.url

class InstallerTests(unittest.TestCase):
    def test_architectures(self):
        self.assertTrue(installer.supported_architecture("AMD64"))
        self.assertFalse(installer.supported_architecture("ARM64"))

    def test_cached_verified_file(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"vendor.exe"
            payload=b"test cache"
            path.write_bytes(payload)
            with patch.object(installer,"EXPECTED_SHA256",hashlib.sha256(payload).hexdigest()), \
                 patch.object(installer,"supported_architecture",return_value=True), \
                 patch("urllib.request.urlopen",side_effect=AssertionError("network should not be used")):
                self.assertEqual(installer.download_official_installer(destination=path),path)

    def test_download_and_checksum(self):
        payload=b"MZ"+b"binary test payload"
        with tempfile.TemporaryDirectory() as d, \
             patch.object(installer,"EXPECTED_SHA256",hashlib.sha256(payload).hexdigest()), \
             patch.object(installer,"supported_architecture",return_value=True), \
             patch("urllib.request.urlopen",return_value=DummyResponse(payload)):
            path=Path(d)/"vendor.exe"
            self.assertEqual(installer.download_official_installer(destination=path),path)
            self.assertEqual(path.read_bytes(),payload)
            self.assertFalse((Path(d)/"vendor.exe.part").exists())

    def test_html_response_then_verified_mirror(self):
        payload=b"MZ"+b"genuine mock data"
        answers=[DummyResponse(b"<!DOCTYPE html><html>try again</html>","text/html"),DummyResponse(payload)]
        with tempfile.TemporaryDirectory() as d, \
             patch.object(installer,"DOWNLOAD_URLS",("https://downloads.sourceforge.net/a", "https://netix.dl.sourceforge.net/b")), \
             patch.object(installer,"EXPECTED_SHA256",hashlib.sha256(payload).hexdigest()), \
             patch.object(installer,"supported_architecture",return_value=True), \
             patch("urllib.request.urlopen",side_effect=answers) as get:
            path=Path(d)/"vendor.exe"
            self.assertEqual(installer.download_official_installer(destination=path),path)
            self.assertEqual(get.call_count,2)
            self.assertEqual(path.read_bytes(),payload)

    def test_mismatching_executable_all_mirrors_blocked(self):
        with tempfile.TemporaryDirectory() as d, \
             patch.object(installer,"DOWNLOAD_URLS",("https://downloads.sourceforge.net/a", "https://netix.dl.sourceforge.net/b")), \
             patch.object(installer,"supported_architecture",return_value=True), \
             patch("urllib.request.urlopen",side_effect=lambda *args,**kwargs: DummyResponse(b"MZbad exe")):
            path=Path(d)/"vendor.exe"
            with self.assertRaisesRegex(installer.InstallerError,"SHA-256"):
                installer.download_official_installer(destination=path)
            self.assertFalse(path.exists())
            self.assertFalse((Path(d)/"vendor.exe.part").exists())

    def test_non_https_redirect_rejected(self):
        with tempfile.TemporaryDirectory() as d, \
             patch.object(installer,"DOWNLOAD_URLS",("https://downloads.sourceforge.net/a",)), \
             patch.object(installer,"supported_architecture",return_value=True), \
             patch("urllib.request.urlopen",return_value=DummyResponse(b"MZtest",url="http://bad.example/test.exe")):
            with self.assertRaisesRegex(installer.InstallerError,"HTTP"):
                installer.download_official_installer(destination=Path(d)/"vendor.exe")

    def test_network_failure_clean_error(self):
        with tempfile.TemporaryDirectory() as d, \
             patch.object(installer,"DOWNLOAD_URLS",("https://downloads.sourceforge.net/a",)), \
             patch.object(installer,"supported_architecture",return_value=True), \
             patch("urllib.request.urlopen",side_effect=URLError("connection blocked")):
            path=Path(d)/"vendor.exe"
            with self.assertRaisesRegex(installer.InstallerError,"зеркал SourceForge"):
                installer.download_official_installer(destination=path)
            self.assertFalse(path.exists())

if __name__=="__main__":
    unittest.main()