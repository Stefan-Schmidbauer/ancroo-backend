"""Centralized STT transcription endpoint for Ancroo Voice clients.

Accepts audio files and forwards them to the configured default STT model.
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
from src.db.models import STTModel
from src.utils.audio import NATIVE_AUDIO_TYPES, AudioConversionError, convert_audio_to_wav
from src.api.v1.dependencies import CurrentUser, DbSession

router = APIRouter(tags=["transcribe"])

logger = logging.getLogger(__name__)


class TranscribeResponse(BaseModel):
    text: str
    model_name: str
    model_id: str


async def _select_stt_model(db) -> STTModel:
    """Select the default active STT model.

    Falls back to the first active model if no default is set.
    """
    # Try default model first
    result = await db.execute(
        select(STTModel)
        .where(STTModel.is_default.is_(True))
        .where(STTModel.is_active.is_(True))
        .limit(1)
    )
    model = result.scalar_one_or_none()

    if model is not None:
        return model

    # Fallback: first active model
    result = await db.execute(
        select(STTModel)
        .where(STTModel.is_active.is_(True))
        .order_by(STTModel.name)
        .limit(1)
    )
    model = result.scalar_one_or_none()

    if model is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No active STT model available. Configure one via the admin panel.",
        )

    return model


@router.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(
    user: CurrentUser,
    db: DbSession,
    file: UploadFile = File(...),
    language: Optional[str] = Form(default=None),
):
    """Transcribe an audio file using the configured default STT model.

    The backend selects the STT server and model — clients only send audio
    and an optional language hint.
    """
    settings = get_settings()

    # Select STT model
    stt_model = await _select_stt_model(db)

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

        # Build request for STT server
        url = f"{stt_model.base_url.rstrip('/')}/v1/audio/transcriptions"
        effective_language = language if language else stt_model.default_language
        form_data = {"model": stt_model.model_id}
        if effective_language:
            form_data["language"] = effective_language

        headers = {}
        if stt_model.api_key:
            headers["Authorization"] = f"Bearer {stt_model.api_key}"

        # Forward audio to STT server
        async with httpx.AsyncClient(timeout=300.0) as client:
            with open(actual_path, "rb") as fh:
                files = {"file": (
                    os.path.basename(actual_path),
                    fh,
                    actual_content_type,
                )}
                response = await client.post(
                    url,
                    data=form_data,
                    files=files,
                    headers=headers,
                )

        if response.status_code != 200:
            logger.error(
                "STT server %s returned %d: %s",
                stt_model.name, response.status_code, response.text[:500],
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
            model_name=stt_model.name,
            model_id=stt_model.model_id,
        )

    except HTTPException:
        raise
    except httpx.HTTPError as e:
        logger.error("STT server '%s' connection failed: %s", stt_model.name, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Cannot reach STT server. Please check your server configuration.",
        )
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        if wav_temp_path and os.path.exists(wav_temp_path):
            os.unlink(wav_temp_path)
