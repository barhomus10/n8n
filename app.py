from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import uuid
import time
import asyncio
from datetime import datetime

app = FastAPI(
    title="Arena Agent API",
    description="API para enviar tareas al agente (videos, imágenes, audio, apps) y recibir resultados. Habla con el agente vía HTTP.",
    version="1.0.0",
)

# CORS abierto para que puedas llamarla desde cualquier frontend / n8n / Zapier / tu app
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Simple in-memory store (en producción usar DB/Redis) ---
tasks: Dict[str, dict] = {}
conversations: Dict[str, List[dict]] = {}

# API Key opcional - por defecto abierto, cámbialo si quieres proteger
API_KEY = "arena-demo-key-2025"  # cámbialo en producción

def verify_api_key(x_api_key: Optional[str] = Header(None), authorization: Optional[str] = Header(None)):
    # Permite X-API-Key o Authorization: Bearer <key>
    # Si no mandas key, igual pasa (modo demo abierto). Descomenta la línea siguiente para exigir key:
    # if not x_api_key and not authorization: raise HTTPException(401, "API Key requerida en X-API-Key o Authorization")
    key = x_api_key or (authorization.replace("Bearer ", "") if authorization else None)
    # En modo demo no bloqueamos si no hay key, pero validamos si la mandan
    if key and key != API_KEY:
        raise HTTPException(401, "API Key inválida")
    return key

# --- Modelos ---
class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None
    stream: Optional[bool] = False

class ChatResponse(BaseModel):
    reply: str
    conversation_id: str
    timestamp: str

class TaskCreate(BaseModel):
    type: str  # video | image | audio | app | chat | custom
    prompt: str
    options: Optional[Dict[str, Any]] = None
    webhook_url: Optional[str] = None

class TaskStatus(BaseModel):
    id: str
    type: str
    prompt: str
    status: str
    progress: int
    result: Optional[Dict[str, Any]] = None
    created_at: str
    updated_at: str

# --- Helpers ---
def now_iso():
    return datetime.utcnow().isoformat() + "Z"

# Simulación de ejecución de tarea (aquí conectas tu lógica real: generar video con ffmpeg, llamar a generate_image, etc.)
async def execute_task(task_id: str):
    task = tasks[task_id]
    # Simula progreso
    for p in [10, 30, 60, 85, 100]:
        await asyncio.sleep(1.2)  # simula trabajo
        task["progress"] = p
        task["status"] = "processing" if p < 100 else "completed"
        task["updated_at"] = now_iso()
        if p == 100:
            # Resultado simulado - aquí pondrías la URL real del archivo generado
            task["result"] = {
                "message": f"Tarea '{task['type']}' completada para prompt: {task['prompt'][:80]}",
                "files": [
                    # Ejemplo: f"/files/{task_id}/video_final.mp4"
                ],
                "download_url": f"/api/v1/tasks/{task_id}/download",
                "preview_url": f"/files/demo/{task_id}.mp4"
            }
    # Si tiene webhook, notificar (opcional)
    if task.get("webhook_url"):
        try:
            import httpx
            async with httpx.AsyncClient() as client:
                await client.post(task["webhook_url"], json=task, timeout=5)
        except:
            pass

@app.get("/", response_class=HTMLResponse)
def home():
    return """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Arena Agent API</title>
<style>
body{font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;color:#111}
code{background:#f3f3f3;padding:2px 6px;border-radius:4px}
pre{background:#0d1117;color:#c9d1d9;padding:16px;border-radius:8px;overflow:auto}
a{color:#0969da}
.card{border:1px solid #ddd;border-radius:12px;padding:20px;margin:16px 0}
.btn{display:inline-block;background:#111;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none}
</style>
</head>
<body>
<h1>🤖 Arena Agent API <span style="font-size:14px;background:#111;color:#fff;padding:4px 8px;border-radius:999px;vertical-align:middle">LIVE</span></h1>
<p>API lista para que me mandes tareas y hables con el agente desde cualquier app, n8n, Zapier, tu web o <code>curl</code>.</p>

<div class="card">
<h3>🌐 URLs</h3>
<p><b>Base URL:</b> <code id="base"></code></p>
<p><b>Docs interactivos (Swagger):</b> <a href="/docs">/docs</a> &nbsp;|&nbsp; <b>ReDoc:</b> <a href="/redoc">/redoc</a></p>
<p><b>Health:</b> <code>GET /health</code></p>
</div>

<div class="card">
<h3>💬 1. Chat con el agente</h3>
<pre>curl -X POST $BASE/api/v1/chat \\
  -H "Content-Type: application/json" \\
  -d '{"message":"Hola, crea un video 20pt con música baja sobre el cerebro"}'</pre>
<p>Respuesta: <code>{ reply, conversation_id }</code></p>
</div>

<div class="card">
<h3>🚀 2. Crear tarea (video / imagen / audio / app)</h3>
<pre>curl -X POST $BASE/api/v1/tasks \\
  -H "Content-Type: application/json" \\
  -H "X-API-Key: arena-demo-key-2025" \\
  -d '{
    "type":"video",
    "prompt":"Video cuadrado 1:1, 90s, sobre generosidad y cerebro, subtítulos 20pt palabra por palabra, música baja",
    "options":{"formato":"1:1","duracion":"90s","subtitulos":"palabra_por_palabra","fontSize":20,"musica":true},
    "webhook_url":"https://tu-webhook.com/callback"
  }'</pre>
<p>Respuesta: <code>{ id, status, progress }</code></p>
</div>

<div class="card">
<h3>📊 3. Consultar tarea / Descargar resultado</h3>
<pre>curl $BASE/api/v1/tasks/{id}
curl $BASE/api/v1/tasks          # lista todas
curl $BASE/api/v1/tasks/{id}/download  # descarga archivo</pre>
</div>

<div class="card">
<h3>🔑 Autenticación</h3>
<p>Demo abierta. Si quieres protegerla, envía header:</p>
<code>X-API-Key: arena-demo-key-2025</code> o <code>Authorization: Bearer arena-demo-key-2025</code>
</div>

<div class="card">
<h3>🧪 Probar aquí mismo</h3>
<textarea id="msg" rows="3" style="width:100%;padding:10px" placeholder="Escribe un mensaje...">Hola agente, crea un video como el anterior pero en vertical 9:16</textarea><br><br>
<button class="btn" onclick="sendChat()">Enviar chat</button>
<button class="btn" style="background:#0969da" onclick="createTask()">Crear tarea video</button>
<pre id="out" style="min-height:80px">Esperando...</pre>
</div>

<script>
document.getElementById('base').textContent = location.origin;
async function sendChat(){
  const msg=document.getElementById('msg').value;
  const r=await fetch('/api/v1/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg})});
  document.getElementById('out').textContent=JSON.stringify(await r.json(),null,2);
}
async function createTask(){
  const r=await fetch('/api/v1/tasks',{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':'arena-demo-key-2025'},body:JSON.stringify({type:'video',prompt:document.getElementById('msg').value,options:{formato:'1:1',fontSize:20}} )});
  document.getElementById('out').textContent=JSON.stringify(await r.json(),null,2);
}
</script>
</body>
</html>
    """

@app.get("/health")
def health():
    return {"status": "ok", "time": now_iso(), "tasks": len(tasks), "version": "1.0.0"}

# --- Chat ---
@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, api_key=Depends(verify_api_key)):
    cid = req.conversation_id or str(uuid.uuid4())[:8]
    if cid not in conversations:
        conversations[cid] = []
    conversations[cid].append({"role": "user", "content": req.message, "time": now_iso()})
    
    # --- Aquí va tu lógica real con LLM ---
    # Por ahora respuesta simulada inteligente. Puedes conectar a OpenAI, Anthropic, tu modelo, o reenviar al agente.
    # Ejemplo con lógica simple:
    lower = req.message.lower()
    if "video" in lower:
        reply = f"✅ Recibido: '{req.message[:80]}' — Puedo generar ese video (1:1, 20pt palabra por palabra + música baja) como el anterior. Si quieres que lo ejecute ya, haz POST /api/v1/tasks con type='video' y tu prompt. ¿Confirmas que lo genere en vertical u horizontal?"
    elif "api" in lower or "url" in lower:
        reply = "La API ya está corriendo. Usa POST /api/v1/tasks para tareas largas (videos, apps) y GET /api/v1/tasks/{id} para ver el progreso. También puedes usar POST /api/v1/chat para hablar. Revisa /docs para probar."
    else:
        reply = f"¡Hola! Soy el agente Arena. Recibí: '{req.message}'. Puedo ayudarte a crear videos (como el de generosidad 20pt + música), imágenes, audios, apps Android, o automatizar tareas. Dime qué tipo de tarea quieres y la lanzo vía /api/v1/tasks. ¿Qué creamos?"
    
    conversations[cid].append({"role": "assistant", "content": reply, "time": now_iso()})
    # Mantener últimas 20
    conversations[cid] = conversations[cid][-20:]
    return {"reply": reply, "conversation_id": cid, "timestamp": now_iso()}

@app.get("/api/v1/conversations/{cid}")
def get_conversation(cid: str):
    if cid not in conversations:
        raise HTTPException(404, "Conversación no encontrada")
    return {"conversation_id": cid, "messages": conversations[cid]}

# --- Tasks ---
@app.post("/api/v1/tasks", response_model=TaskStatus)
async def create_task(req: TaskCreate, background_tasks: Request, api_key=Depends(verify_api_key)):
    tid = str(uuid.uuid4())[:8]
    task = {
        "id": tid,
        "type": req.type,
        "prompt": req.prompt,
        "options": req.options or {},
        "webhook_url": req.webhook_url,
        "status": "queued",
        "progress": 0,
        "result": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    tasks[tid] = task
    # Lanzar ejecución en background
    asyncio.create_task(execute_task(tid))
    return task

@app.get("/api/v1/tasks", response_model=List[TaskStatus])
def list_tasks(api_key=Depends(verify_api_key)):
    return list(tasks.values())[::-1]  # más recientes primero

@app.get("/api/v1/tasks/{task_id}", response_model=TaskStatus)
def get_task(task_id: str, api_key=Depends(verify_api_key)):
    if task_id not in tasks:
        raise HTTPException(404, "Tarea no encontrada")
    return tasks[task_id]

@app.get("/api/v1/tasks/{task_id}/download")
def download_task(task_id: str):
    if task_id not in tasks:
        raise HTTPException(404, "Tarea no encontrada")
    # Demo: si no hay archivo real, devuelve JSON con info
    # En tu caso real, aquí harías FileResponse al mp4 generado en /home/user/video_generosidad/...
    task = tasks[task_id]
    if task["status"] != "completed":
        return JSONResponse({"error": "Tarea aún no completada", "status": task["status"], "progress": task["progress"]}, status_code=202)
    # Intenta servir un archivo real si existe (ejemplo del video final)
    import os
    demo_file = "/home/user/video_generosidad/video_final_20pt_CON_MUSICA_1080.mp4"
    if os.path.exists(demo_file):
        return FileResponse(demo_file, media_type="video/mp4", filename=f"video_{task_id}.mp4")
    return JSONResponse(task["result"])

# --- Webhook test ---
class WebhookTest(BaseModel):
    url: str
    payload: Optional[dict] = None

@app.post("/api/v1/webhook/test")
async def test_webhook(body: WebhookTest):
    import httpx
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(body.url, json=body.payload or {"test": "hola desde Arena API", "time": now_iso()}, timeout=5)
            return {"success": True, "status": r.status_code, "response": r.text[:500]}
    except Exception as e:
        return {"success": False, "error": str(e)}

# Para correr con: uvicorn app:app --host 0.0.0.0 --port 8000
