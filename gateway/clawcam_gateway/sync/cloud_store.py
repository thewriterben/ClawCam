"""Cloud storage backends for off-site media archival.

Abstraction layer so the gateway pipeline can target S3, GCS, or a no-op
stub without changing callsites. The factory function ``get_cloud_store``
picks the right implementation from ``GatewayConfig``.

Design goals
------------
- **Offline-first**: if cloud is not configured, ``NoopStore`` is returned and
  nothing breaks. Uploads are tracked in the DB for later replay.
- **Optional dependencies**: boto3 and google-cloud-storage are never imported
  at module level — they are imported lazily inside ``upload()`` so the gateway
  starts without them installed.
- **Testable**: ``NoopStore`` is always available and deterministic; tests that
  don't pass a real bucket still exercise the upload-tracking path end-to-end.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawcam_gateway.config import GatewayConfig

logger = logging.getLogger(__name__)


class BaseCloudStore(ABC):
    """Interface that all cloud store implementations must satisfy."""

    @property
    @abstractmethod
    def provider(self) -> str:
        """Short provider name used in DB records: 's3', 'gcs', 'noop'."""

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the SDK is installed and basic config looks present."""

    @abstractmethod
    def upload(self, local_path: Path, remote_key: str) -> str:
        """Upload *local_path* to the remote store under *remote_key*.

        Returns the fully-qualified remote URI, e.g.
        ``s3://my-bucket/clawcam/2026-05-14/evt-abc.jpg``.
        Raises ``RuntimeError`` on failure.
        """


class NoopStore(BaseCloudStore):
    """No-operation store used when cloud upload is disabled or unavailable.

    Records the upload attempt and returns a ``noop://`` URI so the tracking
    table still gets populated, making it easy to see what *would* have been
    uploaded.
    """

    @property
    def provider(self) -> str:
        return "noop"

    def is_available(self) -> bool:
        return True

    def upload(self, local_path: Path, remote_key: str) -> str:
        logger.debug("noop upload: %s → noop://%s", local_path, remote_key)
        return f"noop://{remote_key}"


class S3Store(BaseCloudStore):
    """Upload to AWS S3 (or any S3-compatible endpoint such as MinIO/LocalStack).

    Args:
        bucket:       S3 bucket name.
        prefix:       Key prefix prepended to every remote_key (default "clawcam/").
        region:       AWS region (optional; falls back to env/boto3 default).
        endpoint_url: Custom endpoint for MinIO / LocalStack (optional).
    """

    def __init__(
        self,
        bucket: str,
        prefix: str = "clawcam/",
        region: str | None = None,
        endpoint_url: str | None = None,
    ):
        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/" if prefix else ""
        self._region = region
        self._endpoint_url = endpoint_url

    @property
    def provider(self) -> str:
        return "s3"

    def is_available(self) -> bool:
        try:
            import boto3  # noqa: F401
            return bool(self._bucket)
        except ImportError:
            return False

    def upload(self, local_path: Path, remote_key: str) -> str:
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is not installed; install it with: pip install boto3") from exc

        full_key = f"{self._prefix}{remote_key}"
        kwargs: dict = {}
        if self._region:
            kwargs["region_name"] = self._region
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url

        client = boto3.client("s3", **kwargs)
        client.upload_file(str(local_path), self._bucket, full_key)
        uri = f"s3://{self._bucket}/{full_key}"
        logger.info("uploaded %s → %s", local_path.name, uri)
        return uri


class GCSStore(BaseCloudStore):
    """Upload to Google Cloud Storage.

    Args:
        bucket: GCS bucket name.
        prefix: Key prefix prepended to every remote_key (default "clawcam/").
    """

    def __init__(self, bucket: str, prefix: str = "clawcam/"):
        self._bucket = bucket
        self._prefix = prefix.rstrip("/") + "/" if prefix else ""

    @property
    def provider(self) -> str:
        return "gcs"

    def is_available(self) -> bool:
        try:
            from google.cloud import storage  # noqa: F401
            return bool(self._bucket)
        except ImportError:
            return False

    def upload(self, local_path: Path, remote_key: str) -> str:
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise RuntimeError(
                "google-cloud-storage is not installed; "
                "install it with: pip install google-cloud-storage"
            ) from exc

        full_key = f"{self._prefix}{remote_key}"
        client = storage.Client()
        bucket = client.bucket(self._bucket)
        blob = bucket.blob(full_key)
        blob.upload_from_filename(str(local_path))
        uri = f"gs://{self._bucket}/{full_key}"
        logger.info("uploaded %s → %s", local_path.name, uri)
        return uri


def get_cloud_store(config: "GatewayConfig") -> BaseCloudStore:
    """Return the cloud store configured in *config*.

    Falls back to ``NoopStore`` when cloud is disabled or the provider is
    unknown. The caller does not need to handle the disabled case specially.
    """
    if not config.cloud_enabled:
        return NoopStore()

    provider = config.cloud_provider.lower()
    if provider == "s3":
        return S3Store(
            bucket=config.cloud_bucket,
            prefix=config.cloud_prefix,
            region=config.cloud_region,
            endpoint_url=config.cloud_endpoint_url,
        )
    if provider == "gcs":
        return GCSStore(
            bucket=config.cloud_bucket,
            prefix=config.cloud_prefix,
        )

    logger.warning("unknown cloud_provider %r; falling back to noop", provider)
    return NoopStore()
