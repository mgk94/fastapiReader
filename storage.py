import threading
from pathlib import Path
from urllib.parse import urlsplit

from minio import Minio

from config import settings


class ObjectStorageError(RuntimeError):
    pass


def _endpoint_parts(value: str) -> tuple[str, bool]:
    """Convert a configured URL or host:port into MinIO client arguments."""
    raw = value.strip()
    if not raw:
        raise ValueError("MINIO_ENDPOINT must not be empty")

    parsed = urlsplit(raw if "://" in raw else f"//{raw}")
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        raise ValueError("MINIO_ENDPOINT must use http or https")
    if not parsed.netloc or parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError("MINIO_ENDPOINT must contain only a host and optional port")
    return parsed.netloc, parsed.scheme == "https"


class ObjectStorage:
    def __init__(self) -> None:
        endpoint, secure = _endpoint_parts(settings.minio_endpoint)
        self.bucket = settings.minio_bucket
        self.client = Minio(
            endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=secure,
        )
        self._bucket_ready = False
        self._bucket_lock = threading.Lock()

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        with self._bucket_lock:
            if self._bucket_ready:
                return
            try:
                exists = self.client.bucket_exists(self.bucket)
                if not exists:
                    if not settings.minio_auto_create_bucket:
                        raise ObjectStorageError(
                            f"MinIO bucket {self.bucket!r} does not exist"
                        )
                    self.client.make_bucket(self.bucket)
            except ObjectStorageError:
                raise
            except Exception as exc:
                raise ObjectStorageError("Could not access the MinIO bucket") from exc
            self._bucket_ready = True

    def upload_pdf(self, source: Path, object_key: str) -> None:
        self._ensure_bucket()
        try:
            self.client.fput_object(
                self.bucket,
                object_key,
                str(source),
                content_type="application/pdf",
            )
        except Exception as exc:
            raise ObjectStorageError("Could not upload the PDF to MinIO") from exc

    def download_pdf(self, object_key: str, destination: Path) -> None:
        self._ensure_bucket()
        try:
            self.client.fget_object(self.bucket, object_key, str(destination))
        except Exception as exc:
            raise ObjectStorageError("Could not download the PDF from MinIO") from exc

    def delete_objects(self, object_keys: list[str]) -> None:
        self._ensure_bucket()
        try:
            for object_key in object_keys:
                self.client.remove_object(self.bucket, object_key)
        except Exception as exc:
            raise ObjectStorageError("Could not remove PDF objects from MinIO") from exc


object_storage = ObjectStorage()
