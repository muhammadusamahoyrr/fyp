from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.core.rate_limit import limiter
from app.dependencies import get_current_user
from app.services.whisper_service import whisper_service

router = APIRouter(prefix="/voice", tags=["voice"])

MAX_BYTES = 10 * 1024 * 1024  # 10 MB — matches frontend WAV limit for 2-min recording


class TranscriptionResult(BaseModel):
    transcript: str
    language: str
    language_name: str
    language_probability: float


@router.post("/transcribe", response_model=TranscriptionResult)
@limiter.limit("10/minute")
async def transcribe_audio(
    request: Request,
    audio: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    content = await audio.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty audio file.")
    if len(content) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Audio too large. Maximum 10 MB.")

    try:
        # Queued: _alock in the service serialises CPU inference across concurrent requests
        result = await whisper_service.transcribe_async(content, audio.filename or "audio.wav")
    except Exception:
        raise HTTPException(status_code=500, detail="Transcription failed. Please try again.")

    return result
