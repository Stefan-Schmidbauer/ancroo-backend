"""Shared execution log lifecycle helpers to reduce duplication across executors."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import ExecutionLog


def finish_log(
    log: ExecutionLog,
    start_time: datetime,
    *,
    status: str,
    output_preview: Optional[str] = None,
    error_message: Optional[str] = None,
) -> int:
    """Update an execution log with final status and timing.

    Returns duration_ms for convenience.
    """
    end_time = datetime.now(timezone.utc)
    duration_ms = int((end_time - start_time).total_seconds() * 1000)

    log.status = status
    log.completed_at = end_time
    log.duration_ms = duration_ms

    if output_preview is not None:
        log.output_preview = output_preview[:200]
    if error_message is not None:
        log.error_message = error_message

    return duration_ms
