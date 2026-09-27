from fastapi import FastAPI, HTTPException, Header, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import uuid, asyncio, os, subprocess, json
from datetime import datetime
from pathlib import Path

app = FastAPI(title="Arena Agent API - REAL VIDEO", version="2.0.0")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

tasks: Dict[str, dict] = {}
conversations: Dict[str, List[dict]] = {}
API_KEY = os.getenv("API_KEY", "arena-demo-key-2025")
DATA_DIR = Path("/tmp/arena_videos")
DATA_DIR.mkdir(parents=True, exist_ok=True)

def now_iso(): return datetime.utcnow().isoformat()+"Z"

def verify_api_key(x_api_key: Optional[str]=Header(None), authorization: Optional[str]=Header(None)):
    key = x_api_key or (authorization.replace("Bearer ","") if authorization else None)
    if key and key != API_KEY: raise HTTPException(401,"API Key inválida")
    return key

class ChatRequest(BaseModel): message:str; conversation_id:Optional[str]=None
class ChatResponse(BaseModel): reply:str; conversation_id:str; timestamp:str
class TaskCreate(BaseModel): type:str; prompt:str; options:Optional[Dict[str,Any]]=None; webhook_url:Optional[str]=None
class TaskStatus(BaseModel): id:str; type:str; prompt:str; status:str; progress:int; result:Optional[Dict[str,Any]]=None; created_at:str; updated_at:str

def generate_real_video(task_id: str, prompt: str, options: dict):
    """Genera un MP4 REAL con ffmpeg + gTTS + subtítulos palabra por palabra"""
    try:
        from gtts import gTTS
    except ImportError:
        subprocess.run(["pip","install","-q","gTTS"], check=False)
        from gtts import gTTS

    out_mp4 = DATA_DIR / f"{task_id}.mp4"
    tmp_audio = DATA_DIR / f"{task_id}_voice.mp3"
    tmp_srt = DATA_DIR / f"{task_id}.srt"
    tmp_bg = DATA_DIR / f"{task_id}_bg.mp4"

    tts_text = prompt[:800]
    if len(tts_text) < 20: tts_text = "Video generado por Arena Agent. " + prompt
    tts = gTTS(text=tts_text, lang='es', slow=False)
    tts.save(str(tmp_audio))

    try:
        probe = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1", str(tmp_audio)], capture_output=True, text=True)
        duration = float(probe.stdout.strip())
    except:
        duration = 12.0
    duration = max(6, min(duration, 90))

    words = tts_text.split()
    if not words: words = ["Video","Arena"]
    total_chars = sum(len(w) for w in words)
    per_char = duration / total_chars if total_chars else 0.4
    srt_lines=[]
    t=0
    def fmt(s):
        h=int(s//3600); m=int((s%3600)//60); sec=int(s%60); ms=int((s-int(s))*1000)
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
    for i,w in enumerate(words):
        d=len(w)*per_char
        if w.endswith(('.',',','?','!')): d+=0.25
        srt_lines.append(str(i+1))
        srt_lines.append(f"{fmt(t)} --> {fmt(t+d)}")
        srt_lines.append(w)
        srt_lines.append("")
        t+=d
    tmp_srt.write_text("\n".join(srt_lines), encoding="utf-8")

    font_size = int(options.get("fontSize", 20) if isinstance(options,dict) else 20)
    formato = options.get("formato","1:1") if isinstance(options,dict) else "1:1"
    if formato=="9:16": w,h=1080,1920
    elif formato=="16:9": w,h=1920,1080
    else: w,h=1080,1080

    subprocess.run([
        "ffmpeg","-y",
        "-f","lavfi","-i",f"color=c=0x0a1628:s={w}x{h}:d={duration}:r=30",
        "-vf",f"drawbox=x=0:y=0:w={w}:h={h}:color=0x0a1628:t=fill,drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='Arena Agent':fontcolor=white:fontsize=48:x=(w-text_w)/2:y=(h-text_h)/2-200:box=1:boxcolor=black@0.5:boxborderw=10",
        "-pix_fmt","yuv420p","-t",str(duration), str(tmp_bg)
    ], check=True, capture_output=True)

    musica_path = Path("musica_fondo.mp3")
    if not musica_path.exists():
        musica_path = Path("/tmp/arena_videos/musica_fondo.mp3")
        if not musica_path.exists():
            subprocess.run(["ffmpeg","-y","-f","lavfi","-i",f"anullsrc=r=44100:cl=stereo:d={duration}","-t",str(duration),str(musica_path)], capture_output=True)

    filter_v = f"subtitles={tmp_srt}:force_style='FontName=DejaVu Sans,FontSize={font_size},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,BorderStyle=3,Outline=1,Shadow=1,Alignment=2,MarginV=45,Bold=0'"

    subprocess.run([
        "ffmpeg","-y",
        "-i",str(tmp_bg),
        "-i",str(tmp_audio),
        "-i",str(musica_path),
        "-filter_complex",
        f"[0:v]{filter_v}[v];[1:a]volume=1.0[a1];[2:a]volume=0.07,aloop=loop=1:size=2e9,atrim=duration={duration}[a2];[a1][a2]amix=inputs=2:duration=shortest[aout]",
        "-map","[v]","-map","[aout]",
        "-c:v","libx264","-c:a","aac","-pix_fmt","yuv420p","-shortest", str(out_mp4)
    ], check=True, capture_output=True)

    try:
        tmp_bg.unlink(missing_ok=True)
        tmp_audio.unlink(missing_ok=True)
    except: pass
    return str(out_mp4)

async def execute_task(task_id:str):
    task=tasks[task_id]
    try:
        task["status"]="processing"; task["progress"]=10; task["updated_at"]=now_iso()
        await asyncio.sleep(0.5)
        if task["type"]=="video":
            task["progress"]=30
            out_path = await asyncio.to_thread(generate_real_video, task_id, task["prompt"], task.get("options") or {})
            task["progress"]=90
            task["status"]="completed"
            task["result"]={
                "message": f"Video REAL generado: {Path(out_path).name}",
                "files": [str(out_path)],
                "download_url": f"/api/v1/tasks/{task_id}/download",
                "preview_url": f"/api/v1/tasks/{task_id}/download",
                "duration": "auto",
                "fontSize": task.get("options",{}).get("fontSize",20)
            }
        else:
            for p in [40,70,100]:
                await asyncio.sleep(0.6)
                task["progress"]=p
            task["status"]="completed"
            task["result"]={"message": f"Tarea {task['type']} completada: {task['prompt'][:80]}", "download_url": f"/api/v1/tasks/{task_id}/download"}
        task["updated_at"]=now_iso()
    except Exception as e:
        import traceback; traceback.print_exc()
        task["status"]="failed"; task["progress"]=0
        task["result"]={"error": str(e)}
        task["updated_at"]=now_iso()
    if task.get("webhook_url"):
        try:
            import httpx
            async with httpx.AsyncClient() as c:
                await c.post(task["webhook_url"], json=task, timeout=5)
        except: pass

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
def home(request: Request):
    if request.method == "HEAD":
        return HTMLResponse(content="", status_code=200)
    return """
<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Arena Agent API - REAL VIDEO</title>
<style>
body{font-family:system-ui,Segoe UI,Roboto,Helvetica,Arial,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;color:#111}
code{background:#f3f3f3;padding:2px 6px;border-radius:4px}
pre{background:#0d1117;color:#c9d1d9;padding:16px;border-radius:8px;overflow:auto}
a{color:#0969da}
.card{border:1px solid #ddd;border-radius:12px;padding:20px;margin:16px 0}
.btn{display:inline-block;background:#111;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none}
.badge{background:#0a7;font-size:12px;color:#fff;padding:4px 8px;border-radius:999px;vertical-align:middle}
</style>
</head>
<body>
<h1>🤖 Arena Agent API <span class="badge">REAL VIDEO ● LIVE</span></h1>
<p>API permanente en Render — ahora genera <b>MP4 REAL</b> (no simulado) con gTTS + ffmpeg. Habla con el agente vía HTTP.</p>
<div class="card">
<h3>🌐 URLs</h3>
<p><b>Base URL:</b> <code id="base"></code></p>
<p><b>Docs:</b> <a href="/docs">/docs</a> &nbsp;|&nbsp; <b>Health:</b> <code>GET /health</code></p>
</div>
<div class="card">
<h3>💬 1. Chat</h3>
<pre>curl -X POST $BASE/api/v1/chat -H "Content-Type: application/json" -d '{"message":"Hola, crea un video 20pt con música baja"}'</pre>
</div>
<div class="card">
<h3>🚀 2. Crear tarea VIDEO REAL</h3>
<pre>curl -X POST $BASE/api/v1/tasks -H "Content-Type: application/json" -H "X-API-Key: arena-demo-key-2025" -d '{"type":"video","prompt":"Video cuadrado 1:1, 90s, sobre generosidad y cerebro, subtítulos 20pt palabra por palabra, música baja","options":{"formato":"1:1","fontSize":20}}'</pre>
<p>Respuesta: <code>{id, status: queued}</code> → luego <code>GET /api/v1/tasks/{id}</code> hasta <code>completed</code> y <code>GET /download</code> baja el MP4 REAL.</p>
</div>
<div class="card">
<h3>📊 3. Polling</h3>
<pre>curl $BASE/api/v1/tasks/{id} -H "X-API-Key: arena-demo-key-2025"
# cuando completed:
curl $BASE/api/v1/tasks/{id}/download -o video.mp4</pre>
</div>
<div class="card">
<h3>🧪 Probar aquí</h3>
<textarea id="msg" rows="3" style="width:100%;padding:10px" placeholder="Escribe...">Hola agente, crea un video 20pt palabra por palabra con música baja sobre cerebro</textarea><br><br>
<button class="btn" onclick="sendChat()">Enviar chat</button>
<button class="btn" style="background:#0969da" onclick="createTask()">Crear video REAL</button>
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
  const j=await r.json(); document.getElementById('out').textContent=JSON.stringify(j,null,2);
  if(j.id){ let id=j.id; let iv=setInterval(async()=>{
    let s=await (await fetch('/api/v1/tasks/'+id,{headers:{'X-API-Key':'arena-demo-key-2025'}})).json();
    document.getElementById('out').textContent=JSON.stringify(s,null,2);
    if(s.status==='completed'){ clearInterval(iv); document.getElementById('out').textContent+='\\n✅ VIDEO REAL LISTO - descarga en /api/v1/tasks/'+id+'/download'; }
    if(s.status==='failed'){ clearInterval(iv); }
  },2000); }
}
</script>
</body>
</html>
    """

@app.api_route("/health", methods=["GET", "HEAD"])
def health(request: Request = None):
    if request and request.method == "HEAD":
        return JSONResponse(content={}, status_code=200)
    return {"status": "ok", "time": now_iso(), "tasks": len(tasks), "version": "2.0.0-REAL"}

@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(req:ChatRequest):
    cid=req.conversation_id or str(uuid.uuid4())[:8]
    conversations.setdefault(cid,[]).append({"role":"user","content":req.message,"time":now_iso()})
    lower=req.message.lower()
    if "video" in lower: reply=f"✅ Recibido: '{req.message[:80]}' — Generando VIDEO REAL (no simulado) con gTTS + ffmpeg. Usa POST /api/v1/tasks type=video."
    else: reply=f"Hola! Recibí '{req.message[:60]}'. Puedo generar VIDEO REAL ahora. Manda POST /api/v1/tasks."
    conversations[cid].append({"role":"assistant","content":reply,"time":now_iso()})
    return {"reply":reply,"conversation_id":cid,"timestamp":now_iso()}

@app.get("/api/v1/conversations/{cid}")
def get_conversation(cid:str):
    if cid not in conversations: raise HTTPException(404,"Conversación no encontrada")
    return {"conversation_id":cid,"messages":conversations[cid]}

@app.post("/api/v1/tasks")
async def create_task(req:TaskCreate):
    tid=str(uuid.uuid4())[:8]
    task={"id":tid,"type":req.type,"prompt":req.prompt,"options":req.options or {},"webhook_url":req.webhook_url,"status":"queued","progress":0,"result":None,"created_at":now_iso(),"updated_at":now_iso()}
    tasks[tid]=task
    asyncio.create_task(execute_task(tid))
    return task

@app.get("/api/v1/tasks")
def list_tasks(api_key=Depends(verify_api_key)): return list(tasks.values())[::-1]

@app.get("/api/v1/tasks/{task_id}")
def get_task(task_id:str, api_key=Depends(verify_api_key)):
    if task_id not in tasks: raise HTTPException(404,"Tarea no encontrada")
    return tasks[task_id]

@app.get("/api/v1/tasks/{task_id}/download")
def download(task_id:str):
    if task_id not in tasks: raise HTTPException(404,"Tarea no encontrada")
    t=tasks[task_id]
    if t["status"]!="completed": return JSONResponse({"error":"Tarea aún no completada","status":t["status"],"progress":t["progress"]}, status_code=202)
    path = DATA_DIR / f"{task_id}.mp4"
    if path.exists(): return FileResponse(str(path), media_type="video/mp4", filename=f"video_{task_id}.mp4")
    return JSONResponse(t["result"])

class WebhookTest(BaseModel): url:str; payload:Optional[dict]=None
@app.post("/api/v1/webhook/test")
async def test_webhook(body:WebhookTest):
    import httpx
    try:
        async with httpx.AsyncClient() as c:
            r=await c.post(body.url, json=body.payload or {"test":"hola desde Arena API","time":now_iso()}, timeout=5)
            return {"success":True,"status":r.status_code,"response":r.text[:500]}
    except Exception as e: return {"success":False,"error":str(e)}
