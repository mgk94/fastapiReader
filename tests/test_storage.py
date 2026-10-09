import unittest
from pathlib import Path
from threading import Lock
from unittest.mock import Mock

from storage import ObjectStorage, _endpoint_parts


class EndpointPartsTests(unittest.TestCase):
    def test_http_url(self) -> None:
        self.assertEqual(_endpoint_parts("http://minio:9000"), ("minio:9000", False))

    def test_https_url(self) -> None:
        self.assertEqual(
            _endpoint_parts("https://objects.example.com"),
            ("objects.example.com", True),
        )

    def test_host_and_port(self) -> None:
        self.assertEqual(_endpoint_parts("minio:9000"), ("minio:9000", False))

    def test_rejects_path(self) -> None:
        with self.assertRaises(ValueError):
            _endpoint_parts("https://objects.example.com/storage")


class ObjectStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.storage = ObjectStorage.__new__(ObjectStorage)
        self.storage.bucket = "documents"
        self.storage.client = Mock()
        self.storage.client.bucket_exists.return_value = True
        self.storage._bucket_ready = False
        self.storage._bucket_lock = Lock()

    def test_upload_uses_pdf_content_type(self) -> None:
        source = Path("/tmp/source-document.pdf")

        self.storage.upload_pdf(source, "batches/one/document.pdf")

        self.storage.client.fput_object.assert_called_once_with(
            "documents",
            "batches/one/document.pdf",
            str(source),
            content_type="application/pdf",
        )

    def test_download_uses_object_key(self) -> None:
        destination = Path("/tmp/document.pdf")

        self.storage.download_pdf("batches/one/document.pdf", destination)

        self.storage.client.fget_object.assert_called_once_with(
            "documents", "batches/one/document.pdf", str(destination)
        )


if __name__ == "__main__":
    unittest.main()
