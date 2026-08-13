from io import BytesIO
from openai import OpenAI

from ..config import OPENAI_API_KEY


class VoiceService:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)

    def transcribe(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        buf = BytesIO(audio_bytes)
        buf.name = filename
        result = self.client.audio.transcriptions.create(
            model="whisper-1",
            file=buf,
        )
        return result.text

    def synthesize(self, text: str) -> bytes:
        response = self.client.audio.speech.create(
            model="tts-1",
            voice="alloy",
            input=text,
        )
        return response.content
