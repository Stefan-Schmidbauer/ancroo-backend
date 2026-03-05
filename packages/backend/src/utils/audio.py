"""Shared audio utilities for format detection and conversion."""

import logging
import os
import subprocess

logger = logging.getLogger(__name__)

# Audio formats that whisper backends accept directly (no conversion needed)
NATIVE_AUDIO_TYPES = {"audio/wav", "audio/x-wav", "audio/flac", "audio/mpeg", "audio/mp3"}

# File extensions that map to native audio types (fallback when MIME type is wrong)
_NATIVE_EXTENSIONS = {".wav", ".flac", ".mp3", ".mpeg"}
_EXT_TO_MIME = {".wav": "audio/wav", ".flac": "audio/flac", ".mp3": "audio/mp3"}


class AudioConversionError(Exception):
    """Error during audio format conversion."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def _detect_content_type(src_path: str, content_type: str) -> str:
    """Resolve content type from MIME header, falling back to file extension."""
    if content_type in NATIVE_AUDIO_TYPES:
        return content_type
    ext = os.path.splitext(src_path)[1].lower()
    if ext in _EXT_TO_MIME:
        logger.info("MIME type %r unreliable, detected %s from extension", content_type, _EXT_TO_MIME[ext])
        return _EXT_TO_MIME[ext]
    return content_type


def convert_audio_to_wav(src_path: str, content_type: str) -> tuple[str, str, str]:
    """Convert a non-WAV audio file to 16 kHz mono WAV using ffmpeg.

    Returns (new_path, new_content_type, new_filename).
    Raises AudioConversionError when conversion fails.
    """
    content_type = _detect_content_type(src_path, content_type)
    if content_type in NATIVE_AUDIO_TYPES:
        return src_path, content_type, os.path.basename(src_path)

    wav_path = src_path.rsplit(".", 1)[0] + "_converted.wav"
    file_size = os.path.getsize(src_path)
    logger.info(
        "Converting audio: %s (%s, %d bytes) → WAV",
        src_path, content_type, file_size,
    )
    try:
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-err_detect", "ignore_err",   # tolerate minor format errors
                "-i", src_path,
                "-ar", "16000", "-ac", "1",
                "-f", "wav", wav_path,
            ],
            capture_output=True, timeout=30, check=True,
        )
        logger.info("Conversion succeeded: %s", wav_path)
        return wav_path, "audio/wav", os.path.basename(wav_path)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode(errors="replace") if exc.stderr else ""
        logger.error(
            "ffmpeg conversion failed (exit %d, %d bytes input):\n%s",
            exc.returncode, file_size, stderr[-1000:],
        )
        raise AudioConversionError(
            "Audio format not supported. The recording may be too short "
            "or your browser's audio format is not recognized. "
            "Try recording for at least 2 seconds."
        )
    except FileNotFoundError:
        raise AudioConversionError(
            "Audio conversion not available (ffmpeg not installed)"
        )
