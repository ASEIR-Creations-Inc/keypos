from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel, Field


# ── Sync Actions (sent from offline device) ─────────────────────

class SyncAction(BaseModel):
    """One queued action from an offline device."""
    action_type: str  # sale | expense | adjustment | purchase
    payload: dict
    client_ref: str | None = Field(None, max_length=100)
    offline_created_at: datetime | None = None
    auth_token: str | None = Field(None, description="The login the action was made under on the device")


class SyncRequest(BaseModel):
    """Bulk push of offline queue."""
    device_id: str
    actions: list[SyncAction]


# ── Per-action processing result ────────────────────────────────

class SyncActionResult(BaseModel):
    index: int
    action_type: str
    success: bool
    record_id: int | None = None
    duplicate: bool = False
    error: str | None = None


# ── Response for POST /api/sync ─────────────────────────────────

class SyncResponse(BaseModel):
    device_id: str
    received: int
    processed: int
    failed: int
    results: list[SyncActionResult]


# ── Response for GET /api/sync/status ───────────────────────────

class SyncStatusResponse(BaseModel):
    device_id: str
    last_synced_at: datetime | None = None
    pending_count: int = 0
    server_time: datetime
