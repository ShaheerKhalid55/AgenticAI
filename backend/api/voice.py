from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

router = APIRouter(prefix="/api/voice", tags=["voice"])


@router.post("/transcribe")
async def transcribe(file: UploadFile = File(...)):
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
async def synthesize(request: SynthesizeRequest):
    from ..main import services
    try:
        audio = await __import__("asyncio").to_thread(
            services.voice.synthesize,
            request.text,
        )
        return Response(content=audio, media_type="audio/mpeg")
    except Exception as exc:
        raise HTTPException(500, f"TTS error: {exc}")
