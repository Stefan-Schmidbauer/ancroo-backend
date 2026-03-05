"""Centralized STT transcription endpoint for Ancroo Voice clients.

Accepts audio files and forwards them to the configured default STT provider.
Model and server selection is handled server-side — clients only send audio + language.
"""

import logging
import os
from typing import Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy import select

from src.config import get_settings
from src.db.models import STTProvider as STTProviderModel
from src.integrations.stt_provider import _whisper_build_target
from src.utils.audio import NATIVE_AUDIO_TYPES, AudioConversionError, convert_audio_to_wav
from src.api.v1.dependencies import CurrentUser, DbSession

router = APIRouter(tags=["transcribe"])

logger = logging.getLogger(__name__)


class TranscribeResponse(BaseModel):
    text: str
    provider_name: str
    model: str


async def _select_stt_provider(db) -> STTProviderModel:
    """Select the default active STT provider.

    Falls back to the first active provider if no default is set.
    """
    # Try default provider first
    result = await db.execute(
        select(STTProviderModel)
        .where(STTProviderModel.is_default.is_(True))
        .where(STTProviderModel.is_active.is_(True))
        .limit(1)
    )
    provider = result.scalar_one_or_none()

    if provider is not None:
        return provider

    # Fallback: first active provider
    result = await db.execute(
        select(STTProviderModel)
        .where(STTProviderModel.is_active.is_(True))
        .order_by(STTProviderModel.name)
        .limit(1)
    )
    provider = result.scalar_one_or_none()

    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No active STT provider available. Configure one via /admin/stt-providers.",
        )

    return provider


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
    language: Optional[str] = Form(default=None),
):
    """Transcribe an audio file using the configured default STT provider.

    The backend selects the STT server and model — clients only send audio
    and an optional language hint.
    """
    settings = get_settings()

    # Select STT provider
    provider = await _select_stt_provider(db)
    model = provider.default_model

    # Read and validate file
    file_content = await file.read()
    file_size = len(file_content)

    max_size_mb = settings.max_upload_size_mb
    if file_size > max_size_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large: {file_size / 1024 / 1024:.1f} MB (max {max_size_mb} MB)",
        )

    if file_size < 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Recording too short ({file_size} bytes). Please record for at least 1-2 seconds.",
        )

    # Save to temp file for potential conversion
    os.makedirs(settings.upload_temp_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1] or ".wav"
    temp_filename = f"{uuid4()}{ext}"
    temp_path = os.path.join(settings.upload_temp_dir, temp_filename)
    wav_temp_path: str | None = None

    try:
        with open(temp_path, "wb") as f:
            f.write(file_content)

        # Convert non-native audio formats to WAV
        actual_content_type = file.content_type or "application/octet-stream"
        actual_path = temp_path

        if actual_content_type not in NATIVE_AUDIO_TYPES:
            try:
                actual_path, actual_content_type, _ = convert_audio_to_wav(
                    temp_path, actual_content_type,
                )
                if actual_path != temp_path:
                    wav_temp_path = actual_path
            except AudioConversionError as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=e.message,
                )

        # Build target config for the STT server
        target = _whisper_build_target(
            base_url=provider.base_url,
            model=model,
            language=language if language else None,
            timeout=300,
        )

        # Forward audio to STT server
        async with httpx.AsyncClient(timeout=float(target["timeout"])) as client:
            with open(actual_path, "rb") as fh:
                files = {"file": (
                    os.path.basename(actual_path),
                    fh,
                    actual_content_type,
                )}
                response = await client.post(
                    target["url"],
                    data=target["form_fields"],
                    files=files,
                )

        if response.status_code != 200:
            logger.error(
                "STT server %s returned %d: %s",
                provider.name, response.status_code, response.text[:500],
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"STT server error ({response.status_code})",
            )

        result = response.json()
        text = result.get("text", "").strip()

        if not text:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No speech detected in the audio",
            )

        return TranscribeResponse(
            text=text,
            provider_name=provider.name,
            model=model,
        )

    except HTTPException:
        raise
    except httpx.HTTPError as e:
        logger.error("STT server '%s' connection failed: %s", provider.name, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Cannot reach STT server. Please check your server configuration.",
        )
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        if wav_temp_path and os.path.exists(wav_temp_path):
            os.unlink(wav_temp_path)
