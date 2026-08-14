from fastapi import APIRouter, File, UploadFile, HTTPException, Depends
from fastapi.responses import Response
from pydantic import BaseModel

from ..auth.security import get_current_user

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...), current_user: dict = Depends(get_current_user)):
    from ..main import services
    try:
        data = await file.read()
        text = await __import__("asyncio").to_thread(
            services.voice.transcribe,
            data,
            file.filename or "audio.webm",
        )
        return {"text": text}
    except Exception as exc:
        raise HTTPException(500, f"Transcription error: {exc}")


class SynthesizeRequest(BaseModel):
    text: str


@router.post("/synthesize")
async def synthesize(request: SynthesizeRequest, current_user: dict = Depends(get_current_user)):
    from ..main import services
    try:
        audio = await __import__("asyncio").to_thread(
            services.voice.synthesize,
            request.text,
        )
        return Response(content=audio, media_type="audio/mpeg")
    except Exception as exc:
        raise HTTPException(500, f"TTS error: {exc}")
