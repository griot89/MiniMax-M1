import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
import sqlite3
from datetime import datetime
import requests
from dotenv import load_dotenv

# Load environment from g/.env if present
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(ENV_PATH)

# Optional Gemini LLM
try:
    import google.generativeai as genai
except Exception:
    genai = None

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "g_brain", "memory.sqlite")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

app = FastAPI(title="G Assistant API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simple memory store
conn = sqlite3.connect(DB_PATH)
conn.execute("CREATE TABLE IF NOT EXISTS memory (id INTEGER PRIMARY KEY, ts TEXT, role TEXT, content TEXT)")
conn.commit()

class ChatRequest(BaseModel):
    message: str
    system: str | None = None

class TTSRequest(BaseModel):
    text: str
    voice_id: str | None = None

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/chat")
async def chat(req: ChatRequest):
    ts = datetime.utcnow().isoformat()
    conn.execute("INSERT INTO memory (ts, role, content) VALUES (?, ?, ?)", (ts, "user", req.message))
    conn.commit()

    # Choose LLM: Gemini if configured, else fallback echo
    GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
    if genai and GEMINI_KEY:
        try:
            genai.configure(api_key=GEMINI_KEY)
            model = genai.GenerativeModel("gemini-1.5-flash")
            sysmsg = req.system or "You are G, a helpful, capable personal AI assistant with a warm, concise, optimistic style. Ask before taking impactful actions."
            prompt = f"System: {sysmsg}\nUser: {req.message}"
            resp = model.generate_content(prompt)
            reply = resp.text if hasattr(resp, 'text') and resp.text else "(no content)"
        except Exception as e:
            reply = f"[G] (Gemini error) {e}. Echo: {req.message}"
    else:
        reply = f"[G] {req.message}"

    conn.execute("INSERT INTO memory (ts, role, content) VALUES (?, ?, ?)", (ts, "assistant", reply))
    conn.commit()
    return {"reply": reply}

@app.get("/export")
async def export_memory():
    rows = conn.execute("SELECT ts, role, content FROM memory ORDER BY id ASC").fetchall()
    return JSONResponse([{ "ts": r[0], "role": r[1], "content": r[2]} for r in rows])

ELEVEN_API_KEY = os.environ.get("ELEVENLABS_API_KEY")
DEFAULT_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "Z8dg0fyk7p6js7cQ7lgi")

@app.post("/tts")
async def tts(req: TTSRequest):
    if not ELEVEN_API_KEY:
        raise HTTPException(status_code=500, detail="ELEVENLABS_API_KEY not configured on server")
    voice_id = req.voice_id or DEFAULT_VOICE_ID
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = {
        "text": req.text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}
    }
    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json"
    }
    try:
        r = requests.post(url, json=payload, headers=headers, stream=True, timeout=60)
        if r.status_code != 200:
            detail = r.text[:500]
            raise HTTPException(status_code=502, detail=f"TTS failed ({r.status_code}): {detail}")
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"TTS request error: {e}")

    return StreamingResponse(r.iter_content(chunk_size=8192), media_type="audio/mpeg")

@app.get("/voice")
async def voice_info():
    return {"default_voice_id": DEFAULT_VOICE_ID, "configured": bool(ELEVEN_API_KEY)}

# Basic websocket for realtime text (no audio yet)
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            data = await ws.receive_text()
            ts = datetime.utcnow().isoformat()
            conn.execute("INSERT INTO memory (ts, role, content) VALUES (?, ?, ?)", (ts, "user", data))
            conn.commit()
            reply = f"[G] You said: {data}"
            conn.execute("INSERT INTO memory (ts, role, content) VALUES (?, ?, ?)", (ts, "assistant", reply))
            conn.commit()
            await ws.send_text(reply)
    except WebSocketDisconnect:
        pass
