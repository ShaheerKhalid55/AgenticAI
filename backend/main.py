from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .config import CORS_ORIGINS
from .services.mongo import MongoService
from .services.qdrant import QdrantService
from .services.voice import VoiceService
from .agent.graph import AgentService
from importlib.resources import files

from .api import chat, sessions, documents, voice, health


class Services:
    mongo = None
    qdrant = None
    voice = None
    agent = None


services = Services()


@asynccontextmanager
async def lifespan(app: FastAPI):
    services.mongo = MongoService()
    services.qdrant = QdrantService()
    services.voice = VoiceService()
    services.agent = AgentService(services.qdrant, services.mongo)
    await services.agent.initialize()
    yield


app = FastAPI(
    title="HR Policy Assistant API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(sessions.router)
app.include_router(documents.router)
app.include_router(voice.router)
app.include_router(health.router)

frontend = files("frontend")

app.mount(
    "/",
    StaticFiles(directory=str(frontend), html=True),
    name="frontend"
)
