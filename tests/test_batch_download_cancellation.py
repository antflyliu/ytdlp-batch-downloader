"""Cancellation tests for batch_download()."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_ROOT))


class TestBatchDownloadCancellation(unittest.TestCase):
    def test_batch_download_raises_cancelled_before_processing_next_url(self):
        from Youtube_Downloader import BatchDownloadCancelled, batch_download

        with tempfile.TemporaryDirectory() as tmpdir:
            with mock.patch("Youtube_Downloader.get_device", return_value="cpu"):
                with self.assertRaises(BatchDownloadCancelled):
                    batch_download(
                        ["https://youtube.com/watch?v=1"],
                        tmpdir,
                        "best",
                        should_cancel=lambda: True,
                    )


if __name__ == "__main__":
    unittest.main()
