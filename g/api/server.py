import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import sqlite3
from datetime import datetime

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

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/chat")
async def chat(req: ChatRequest):
    # Minimal echo with timestamp; real LLM integration later
    ts = datetime.utcnow().isoformat()
    conn.execute("INSERT INTO memory (ts, role, content) VALUES (?, ?, ?)", (ts, "user", req.message))
    conn.commit()
    reply = f"[G] I heard: {req.message}"  # placeholder
    conn.execute("INSERT INTO memory (ts, role, content) VALUES (?, ?, ?)", (ts, "assistant", reply))
    conn.commit()
    return {"reply": reply}

@app.get("/export")
async def export_memory():
    rows = conn.execute("SELECT ts, role, content FROM memory ORDER BY id ASC").fetchall()
    return JSONResponse([{ "ts": r[0], "role": r[1], "content": r[2]} for r in rows])

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
