# Livery pictures from the MTL catalog: downloaded once, kept in the previews folder, failures remembered.
# The network is never used: urllib.request.urlopen is replaced.

import threading
import time
import urllib.error
from unittest import mock

from support import TempDirTestCase, vmr_gui


class FakeResponse:
    def __init__(self, data=b"PNGDATA", content_type="image/png", delay=0):
        self.data, self.headers, self.delay = data, {"Content-Type": content_type}, delay

    def read(self):
        time.sleep(self.delay)
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class PreviewsTest(TempDirTestCase):
    def setUp(self):
        super().setUp()
        self.previews = vmr_gui.Previews(self.tmp / "previews")

    def test_downloads_once_and_keeps_the_file(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
            first = self.previews.get(42)
            second = self.previews.get(42)
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(first.name, "42.png")
        self.assertEqual(first.read_bytes(), b"PNGDATA")
        request = urlopen.call_args[0][0]
        self.assertEqual(request.full_url, vmr_gui.CATALOG_IMAGE.format(id=42))
        self.assertEqual(list((self.tmp / "previews").iterdir()), [first])  # no .part file left behind

    def test_extension_from_content_type(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(content_type="image/webp; charset=binary")):
            self.assertEqual(self.previews.get(7).name, "7.webp")

    def test_cached_file_needs_no_network(self):
        (self.tmp / "previews").mkdir()
        (self.tmp / "previews" / "5.jpg").write_bytes(b"x")
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("no network")):
            self.assertEqual(self.previews.get(5).name, "5.jpg")

    def test_not_a_picture(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(content_type="text/html")) as urlopen, \
             mock.patch("builtins.print"):
            self.assertIsNone(self.previews.get(9))
            self.assertIsNone(self.previews.get(9))
        self.assertEqual(urlopen.call_count, 1)  # the failure is remembered
        self.assertIn(9, self.previews.failed)
        self.assertFalse((self.tmp / "previews").exists())

    def test_no_network(self):
        with mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")), mock.patch("builtins.print"):
            self.assertIsNone(self.previews.get(3))
        self.assertIn("offline", self.previews.failed[3])

    def test_parallel_requests_download_once(self):
        with mock.patch("urllib.request.urlopen", return_value=FakeResponse(delay=0.2)) as urlopen:
            results = []
            threads = [threading.Thread(target=lambda: results.append(self.previews.get(11))) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(urlopen.call_count, 1)
        self.assertEqual(len(set(results)), 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
