"""Background cloud upload worker for ClawCam media files.

``CloudUploadWorker`` is the single callsite used by the inference pipeline
and the media upload endpoint. It:

1. Inserts a ``cloud_uploads`` row with status="pending".
2. Attempts the upload via the configured ``BaseCloudStore``.
3. Updates the row to "uploaded" (with remote_uri) or "failed" (with error).

Design notes
------------
- Runs synchronously inside a FastAPI ``BackgroundTask`` — no threads needed.
- The ``NoopStore`` path always succeeds, so existing deployments are unaffected.
- Failed uploads stay in the DB and can be retried; future work can add a
  periodic retry loop.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from clawcam_gateway.storage.database import GatewayDatabase
    from clawcam_gateway.sync.cloud_store import BaseCloudStore

logger = logging.getLogger(__name__)


class CloudUploadWorker:
    """Coordinate media uploads to cloud storage and persist their status."""

    def __init__(self, db: "GatewayDatabase", store: "BaseCloudStore"):
        self.db = db
        self.store = store

    def queue_and_upload(
        self,
        local_path: Path,
        event_id: str | None = None,
        remote_key: str | None = None,
    ) -> dict:
        """Upload *local_path* and record the result in ``cloud_uploads``.

        Args:
            local_path:  Absolute path to the file on disk.
            event_id:    Associated gateway event_id (may be None for firmware etc).
            remote_key:  Remote object key. Defaults to ``<event_id>/<filename>``
                         or just ``<filename>`` when event_id is None.

        Returns a dict with keys: upload_id, status, remote_uri, error.
        """
        if remote_key is None:
            name = local_path.name
            remote_key = f"{event_id}/{name}" if event_id else name

        upload_id = self.db.add_cloud_upload(
            event_id=event_id,
            media_path=str(local_path),
            provider=self.store.provider,
        )

        if not local_path.exists():
            error = f"local file not found: {local_path}"
            logger.warning("cloud upload skipped — %s", error)
            self.db.update_cloud_upload(upload_id, status="failed", error=error)
            return {"upload_id": upload_id, "status": "failed", "remote_uri": None, "error": error}

        try:
            remote_uri = self.store.upload(local_path, remote_key)
            self.db.update_cloud_upload(
                upload_id,
                status="uploaded",
                remote_uri=remote_uri,
                uploaded_at=datetime.now(timezone.utc).isoformat(),
            )
            logger.info("cloud upload ok: %s → %s", local_path.name, remote_uri)
            return {"upload_id": upload_id, "status": "uploaded", "remote_uri": remote_uri, "error": None}
        except Exception as exc:  # noqa: BLE001 - worker must not crash caller
            error = str(exc)
            logger.error("cloud upload failed for %s: %s", local_path.name, error)
            self.db.update_cloud_upload(upload_id, status="failed", error=error)
            return {"upload_id": upload_id, "status": "failed", "remote_uri": None, "error": error}
