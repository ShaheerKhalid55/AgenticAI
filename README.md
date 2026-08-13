# HR Policy Assistant — FastAPI + HTML/JS

This is the FastAPI/frontend migration of the Streamlit HR Policy Assistant.

## Architecture

- FastAPI API/backend
- HTML/CSS/JavaScript frontend
- LangGraph agent
- Ollama Cloud / Gemma
- MXBAI local embeddings
- Qdrant policy and long-term memory
- MongoDB LangGraph checkpoints and session metadata
- LangMem memory tools
- MCP fetch tool
- OpenAI Whisper STT
- OpenAI TTS

## Run

1. Create a Python virtual environment.
2. Install:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and configure credentials.

4. Start:

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

5. Open:

http://localhost:8000

## Important

The application expects the MCP module used by the original application:

```text
mcp_server_fetch
```

to be importable from the same Python environment.

The first startup loads the MXBAI embedding model. This can take time and requires the model to be available locally.

## API docs

Once running:

http://localhost:8000/docs
