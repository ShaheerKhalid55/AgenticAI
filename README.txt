HR Policy Assistant - Frontend Fix

Replace ALL THREE files together:
frontend/index.html
frontend/css/styles.css
frontend/js/app.js

Do not keep the old sessions.js or voice.js script references in index.html.

Restart FastAPI:
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

Then hard refresh Chrome:
Ctrl + Shift + R

Verify CSS directly:
http://localhost:8000/css/styles.css

If that URL shows CSS text, static files are mounted correctly.
