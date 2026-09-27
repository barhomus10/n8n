from fastapi import FastAPI, HTTPException, Header, Depends, Request, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import uuid, asyncio, os, subprocess, json, time, base64, hashlib
from datetime import datetime
from pathlib import Path
import textwrap

app = FastAPI(title="Arena Agent API - TODO EN UNO", version="3.0.0", description="LLM + Vision + Imagen + Video REAL + Voz + RAG")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Stores
tasks: Dict[str, dict] = {}
conversations: Dict[str, List[dict]] = {}
knowledge_store: Dict[str, dict] = {}  # id -> {text, embedding mock, metadata}
API_KEY = os.getenv("API_KEY", "arena-demo-key-2025")
DATA_DIR = Path("/tmp/arena_videos")
DATA_DIR.mkdir(parents=True, exist_ok=True)

def now_iso(): return datetime.utcnow().isoformat()+"Z"
def verify_api_key(x_api_key: Optional[str]=Header(None), authorization: Optional[str]=Header(None)):
    key = x_api_key or (authorization.replace("Bearer ","") if authorization else None)
    if key and key != API_KEY: raise HTTPException(401,"API Key inválida")
    return key

# ========== MODELS ==========
class ChatRequest(BaseModel): message:str; conversation_id:Optional[str]=None
class ChatResponse(BaseModel): reply:str; conversation_id:str; timestamp:str
class TaskCreate(BaseModel): type:str; prompt:str; options:Optional[Dict[str,Any]]=None; webhook_url:Optional[str]=None
class TaskStatus(BaseModel): id:str; type:str; prompt:str; status:str; progress:int; result:Optional[Dict[str,Any]]=None; created_at:str; updated_at:str
class OpenAIChatMessage(BaseModel): role:str; content:str
class OpenAIChatRequest(BaseModel): model:Optional[str]="arena-llm"; messages:List[OpenAIChatMessage]; temperature:Optional[float]=0.7; max_tokens:Optional[int]=1024; stream:Optional[bool]=False
class ImageGenRequest(BaseModel): prompt:str; size:Optional[str]="1024x1024"; n:Optional[int]=1; style:Optional[str]="realista"
class TTSRequest(BaseModel): text:str; voice:Optional[str]="masculina"; lang:Optional[str]="es"; speed:Optional[float]=1.0
class TranslateRequest(BaseModel): text:str; source:Optional[str]="auto"; target:str="es"
class SummarizeRequest(BaseModel): text:str; max_length:Optional[int]=150
class VisionRequest(BaseModel): image_url:Optional[str]=None; image_base64:Optional[str]=None; question:Optional[str]="Describe esta imagen"
class RAGUpload(BaseModel): text:str; metadata:Optional[Dict[str,Any]]=None; id:Optional[str]=None
class RAGQuery(BaseModel): query:str; top_k:Optional[int]=3

# ========== REAL VIDEO GEN - TXT-TO-VIDEO ANIMADO CON IMÁGENES REALES ==========
def generate_real_video(task_id: str, prompt: str, options: dict):
    """TXT-TO-VIDEO REAL: genera imágenes con modelo txt-to-image y las anima con ffmpeg + gTTS + subtítulos palabra por palabra"""
    try:
        from gtts import gTTS
    except ImportError:
        subprocess.run(["pip","install","-q","gTTS"], check=False)
        from gtts import gTTS
    import httpx, random, urllib.parse
    out_mp4 = DATA_DIR / f"{task_id}.mp4"
    tmp_audio = DATA_DIR / f"{task_id}_voice.mp3"
    tmp_srt = DATA_DIR / f"{task_id}.srt"
    tmp_concat = DATA_DIR / f"{task_id}_concat.txt"
    tmp_slideshow = DATA_DIR / f"{task_id}_slideshow.mp4"

    # 1. Audio TTS
    tts_text = prompt[:800]
    if len(tts_text) < 20: tts_text = "Video generado por Arena Agent. " + prompt
    lang = options.get("lang","es") if isinstance(options,dict) else "es"
    try:
        tts = gTTS(text=tts_text, lang=lang, slow=False)
        tts.save(str(tmp_audio))
    except Exception as e:
        # fallback: silencio + texto
        subprocess.run(["ffmpeg","-y","-f","lavfi","-i","anullsrc=r=24000:cl=mono:d=10","-t","10",str(tmp_audio)], capture_output=True)
        tts_text = prompt  # para SRT igual
    try:
        probe = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration","-of","default=noprint_wrappers=1:nokey=1", str(tmp_audio)], capture_output=True, text=True)
        duration = float(probe.stdout.strip())
    except: duration = 15.0
    duration = max(8, min(duration, 90))

    # 2. SRT palabra por palabra
    words = tts_text.split()
    total_chars = sum(len(w) for w in words) or 1
    per_char = duration / total_chars
    srt_lines=[]; t=0
    def fmt(s):
        h=int(s//3600); m=int((s%3600)//60); sec=int(s%60); ms=int((s-int(s))*1000)
        return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"
    for i,w in enumerate(words):
        d=len(w)*per_char + (0.25 if w.endswith(('.',',','?','!')) else 0)
        srt_lines += [str(i+1), f"{fmt(t)} --> {fmt(t+d)}", w, ""]
        t+=d
    tmp_srt.write_text("\n".join(srt_lines), encoding="utf-8")
    font_size = int(options.get("fontSize",20) if isinstance(options,dict) else 20)
    estilo = options.get("estilo","realista") if isinstance(options,dict) else "realista"
    formato = options.get("formato","1:1") if isinstance(options,dict) else "1:1"
    w,h = (1080,1920) if formato=="9:16" else (1920,1080) if formato=="16:9" else (1080,1080)

    # 3. Generar imágenes con modelo txt-to-image REAL (Pollinations + fallback)
    # Creamos 5 escenas a partir del prompt
    base_prompt = prompt[:120]
    # Si el prompt es sobre cerebro/generosidad, creamos escenas temáticas; si no, genéricas
    if any(k in prompt.lower() for k in ["cerebro","generosidad","neurona","ciencia"]):
        scene_prompts = [
            f"{base_prompt}, human brain glowing neural networks, blue orange bokeh, scientific cinematic, 8k",
            f"{base_prompt}, neuroscience laboratory MRI scanner volunteers, documentary realistic",
            f"anatomical transparent head showing temporo-parietal junction glowing gold, medical illustration",
            f"{base_prompt}, hands helping each other with neural network overlay, hopeful warm light",
            f"{base_prompt}, diverse friends sharing and laughing at sunset, inspirational cinematic"
        ]
    else:
        # Genérico: divide prompt en 5 variaciones
        scene_prompts = [f"{base_prompt}, scene {i+1}, {estilo}, cinematic, high detail 8k, vibrant" for i in range(5)]

    num_scenes = len(scene_prompts)
    per_scene = duration / num_scenes
    img_paths = []
    for idx, sp in enumerate(scene_prompts):
        img_path = DATA_DIR / f"{task_id}_img{idx}.jpg"
        # Intenta descargar de Pollinations (txt-to-image real, sin API key)
        # Usa seed aleatorio para variedad
        seed = random.randint(1, 999999)
        # Pollinations: https://image.pollinations.ai/p/{prompt}?width=1024&height=1024&seed=...&model=flux
        encoded = urllib.parse.quote(sp)
        url = f"https://image.pollinations.ai/p/{encoded}?width={w}&height={h}&seed={seed}&model=flux&enhance=true&nologo=true"
        success=False
        for attempt in range(2):
            try:
                with httpx.Client(timeout=20) as client:
                    r = client.get(url, follow_redirects=True)
                    if r.status_code==200 and len(r.content) > 8000:
                        img_path.write_bytes(r.content)
                        success=True
                        break
            except: pass
            # fallback URL sin model param
            try:
                url2 = f"https://image.pollinations.ai/p/{encoded}?width={w}&height={h}&seed={seed}"
                with httpx.Client(timeout=20) as client:
                    r = client.get(url2, follow_redirects=True)
                    if r.status_code==200 and len(r.content) > 8000:
                        img_path.write_bytes(r.content)
                        success=True
                        break
            except: pass
        if not success or not img_path.exists():
            # Fallback: genera imagen placeholder con PIL + texto
            try:
                from PIL import Image, ImageDraw, ImageFont
                img = Image.new('RGB', (w,h), color=(10,22,40))
                d = ImageDraw.Draw(img)
                try: font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 36)
                except: font = ImageFont.load_default()
                d.text((50,h//2-100), textwrap.fill(sp[:80], width=30), fill=(255,255,255), font=font)
                d.text((50,h//2+80), f"Escena {idx+1}/{num_scenes}", fill=(180,220,255), font=font)
                img.save(img_path, "JPEG")
            except:
                # último fallback: color sólido con ffmpeg
                subprocess.run(["ffmpeg","-y","-f","lavfi","-i",f"color=c=0x0a1628:s={w}x{h}:d=1:r=30","-vframes","1",str(img_path)], capture_output=True)
        img_paths.append(img_path)

    # 4. Crear slideshow animado (Ken Burns sutil + concat)
    # Crea concat demuxer file
    with open(tmp_concat, "w") as f:
        for p in img_paths:
            f.write(f"file '{p}'\n")
            f.write(f"duration {per_scene}\n")
        # último frame necesita repetirse para concat
        f.write(f"file '{img_paths[-1]}'\n")
    # Genera slideshow con zoompan sutil y escala a tamaño final
    # Usa: scale + zoompan para animar cada imagen
    # Para simplicidad, usamos concat + fps + scale/crop con zoompan por imagen vía filter_complex
    # Aquí hacemos un slideshow simple con crossfade suave: primero genera video sin zoom, luego añade zoompan en un segundo paso sería complejo.
    # Implementamos un slideshow con zoom lento usando cada imagen con zoompan y luego concat.
    # Para no complicar, hacemos un video base con concat y luego aplicamos un ligero zoom global + subtítulos
    subprocess.run([
        "ffmpeg","-y",
        "-f","concat","-safe","0","-i",str(tmp_concat),
        "-vf",f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=30,zoompan=z='min(zoom+0.0012,1.35)':d=700:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps=30",
        "-t",str(duration),
        "-pix_fmt","yuv420p",
        str(tmp_slideshow)
    ], check=True, capture_output=True)

    # 5. Música de fondo
    musica_path = Path("musica_fondo.mp3")
    if not musica_path.exists():
        musica_path = Path("/tmp/arena_videos/musica_fondo.mp3")
        if not musica_path.exists():
            subprocess.run(["ffmpeg","-y","-f","lavfi","-i",f"anullsrc=r=44100:cl=stereo:d={duration}","-t",str(duration),str(musica_path)], capture_output=True)

    filter_v = f"subtitles={tmp_srt}:force_style='FontName=DejaVu Sans,FontSize={font_size},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H80000000,BorderStyle=3,Outline=1,Shadow=1,Alignment=2,MarginV=45,Bold=0'"

    subprocess.run([
        "ffmpeg","-y",
        "-i",str(tmp_slideshow),
        "-i",str(tmp_audio),
        "-i",str(musica_path),
        "-filter_complex",
        f"[0:v]{filter_v}[v];[1:a]volume=1.0[a1];[2:a]volume=0.07,aloop=loop=1:size=2e9,atrim=duration={duration}[a2];[a1][a2]amix=inputs=2:duration=shortest[aout]",
        "-map","[v]","-map","[aout]",
        "-c:v","libx264","-c:a","aac","-pix_fmt","yuv420p","-shortest", str(out_mp4)
    ], check=True, capture_output=True)

    # Limpieza
    try:
        for p in img_paths: p.unlink(missing_ok=True)
        tmp_concat.unlink(missing_ok=True)
        tmp_slideshow.unlink(missing_ok=True)
        tmp_audio.unlink(missing_ok=True)
    except: pass
    return str(out_mp4)

async def execute_task(task_id:str):
    task=tasks[task_id]
    try:
        task["status"]="processing"; task["progress"]=10; task["updated_at"]=now_iso()
        await asyncio.sleep(0.3)
        ttype=task["type"]
        if ttype=="video":
            task["progress"]=30
            out_path = await asyncio.to_thread(generate_real_video, task_id, task["prompt"], task.get("options") or {})
            task["progress"]=90; task["status"]="completed"
            task["result"]={"message": f"Video REAL generado","files":[str(out_path)],"download_url":f"/api/v1/tasks/{task_id}/download","preview_url":f"/api/v1/tasks/{task_id}/download","fontSize":task.get("options",{}).get("fontSize",20)}
        elif ttype=="image":
            # Simula generación real - en tu laptop podrías llamar a generate_image
            await asyncio.sleep(1)
            task["progress"]=70
            # Crea una imagen placeholder con PIL
            from PIL import Image, ImageDraw, ImageFont
            img_path = DATA_DIR / f"{task_id}.jpg"
            img = Image.new('RGB', (1024,1024), color=(10,22,40))
            d = ImageDraw.Draw(img)
            try: font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
            except: font = ImageFont.load_default()
            prompt = task["prompt"][:80]
            d.text((50,500), textwrap.fill(prompt, width=30), fill=(255,255,255), font=font)
            img.save(img_path)
            task["progress"]=100; task["status"]="completed"
            task["result"]={"message":"Imagen generada (placeholder, conecta tu generate_image para real)","files":[str(img_path)],"download_url":f"/api/v1/tasks/{task_id}/download","prompt":task["prompt"]}
        elif ttype=="audio":
            # TTS real con gTTS
            from gtts import gTTS
            audio_path = DATA_DIR / f"{task_id}.mp3"
            gTTS(text=task["prompt"][:500], lang='es').save(str(audio_path))
            task["status"]="completed"; task["progress"]=100
            task["result"]={"message":"Audio TTS generado","files":[str(audio_path)],"download_url":f"/api/v1/tasks/{task_id}/download"}
        else:
            for p in [40,70,100]:
                await asyncio.sleep(0.6); task["progress"]=p
            task["status"]="completed"
            task["result"]={"message": f"Tarea {ttype} completada: {task['prompt'][:80]}", "download_url": f"/api/v1/tasks/{task_id}/download"}
        task["updated_at"]=now_iso()
    except Exception as e:
        import traceback; traceback.print_exc()
        task["status"]="failed"; task["result"]={"error":str(e)}; task["updated_at"]=now_iso()
    if task.get("webhook_url"):
        try:
            import httpx
            async with httpx.AsyncClient() as c: await c.post(task["webhook_url"], json=task, timeout=5)
        except: pass

# ========== HOME ==========
@app.api_route("/", methods=["GET","HEAD"], response_class=HTMLResponse)
def home(request: Request):
    if request.method=="HEAD": return HTMLResponse("", status_code=200)
    return """
<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Arena Agent API - TODO EN UNO</title>
<style>body{font-family:system-ui,Segoe UI,Roboto,sans-serif;max-width:1000px;margin:40px auto;padding:0 20px;color:#111}
code{background:#f3f3f3;padding:2px 6px;border-radius:4px}pre{background:#0d1117;color:#c9d1d9;padding:16px;border-radius:8px;overflow:auto}
a{color:#0969da}.card{border:1px solid #ddd;border-radius:12px;padding:20px;margin:16px 0}
.badge{background:#0a7;color:#fff;padding:4px 8px;border-radius:999px;font-size:12px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px} .btn{background:#111;color:#fff;padding:10px 16px;border-radius:8px;text-decoration:none;display:inline-block}
</style></head><body>
<h1>🤖 Arena Agent API <span class="badge">TODO EN UNO v3 ● LIVE</span></h1>
<p>Una sola URL para todos tus modelos LLM: chat, visión, imagen, video REAL, voz, RAG, traducción.</p>
<p><b>Base:</b> <code id="base"></code> | <b>Docs:</b> <a href="/docs">/docs</a> | <b>Health:</b> <code>/health</code></p>
<div class="grid">
<div class="card"><h3>💬 LLM</h3><code>POST /v1/chat/completions</code><br><code>POST /api/v1/chat</code></div>
<div class="card"><h3>👁️ Visión</h3><code>POST /v1/vision</code><br><code>POST /api/v1/ocr</code></div>
<div class="card"><h3>🎨 Imagen</h3><code>POST /v1/images/generations</code><br><code>POST /api/v1/tasks type=image</code></div>
<div class="card"><h3>🎬 Video REAL</h3><code>POST /api/v1/tasks type=video</code> (20pt palabra por palabra + música)</div>
<div class="card"><h3>🔊 Voz</h3><code>POST /v1/audio/speech</code> TTS<br><code>POST /v1/audio/transcriptions</code></div>
<div class="card"><h3>📚 RAG</h3><code>POST /v1/knowledge/upload</code><br><code>POST /v1/knowledge/query</code></div>
<div class="card"><h3>🌍 Utils</h3><code>POST /v1/translate</code><br><code>POST /v1/summarize</code></div>
<div class="card"><h3>⚙️ Tasks</h3><code>POST /api/v1/tasks</code><br><code>GET /api/v1/tasks/{id}</code></div>
</div>
<div class="card">
<h3>🧪 Probar</h3>
<textarea id="msg" rows="3" style="width:100%;padding:10px">Hola, crea un video 20pt palabra por palabra con música baja sobre cerebro</textarea><br><br>
<button class="btn" onclick="sendChat()">Chat</button>
<button class="btn" style="background:#0969da" onclick="createTask()">Video REAL</button>
<button class="btn" style="background:#0a7" onclick="testImage()">Imagen</button>
<pre id="out" style="min-height:80px">Esperando...</pre>
</div>
<script>
document.getElementById('base').textContent=location.origin;
async function sendChat(){const r=await fetch('/api/v1/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:document.getElementById('msg').value})}); document.getElementById('out').textContent=JSON.stringify(await r.json(),null,2)}
async function createTask(){const r=await fetch('/api/v1/tasks',{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':'arena-demo-key-2025'},body:JSON.stringify({type:'video',prompt:document.getElementById('msg').value,options:{fontSize:20}})}); const j=await r.json(); document.getElementById('out').textContent=JSON.stringify(j,null,2); if(j.id){let id=j.id; let iv=setInterval(async()=>{let s=await (await fetch('/api/v1/tasks/'+id,{headers:{'X-API-Key':'arena-demo-key-2025'}})).json(); document.getElementById('out').textContent=JSON.stringify(s,null,2); if(s.status==='completed'){clearInterval(iv); document.getElementById('out').textContent+='\\n✅ VIDEO REAL LISTO /download';}},2000)}}
async function testImage(){const r=await fetch('/v1/images/generations',{method:'POST',headers:{'Content-Type':'application/json','X-API-Key':'arena-demo-key-2025'},body:JSON.stringify({prompt:document.getElementById('msg').value})}); document.getElementById('out').textContent=JSON.stringify(await r.json(),null,2)}
</script>
</body></html>
    """

@app.api_route("/health", methods=["GET","HEAD"])
def health(request: Request=None):
    if request and request.method=="HEAD": return JSONResponse({}, status_code=200)
    return {"status":"ok","time":now_iso(),"tasks":len(tasks),"knowledge":len(knowledge_store),"version":"3.0.0"}

# ========== CHAT SIMPLE ==========
@app.post("/api/v1/chat", response_model=ChatResponse)
async def chat(req:ChatRequest):
    cid=req.conversation_id or str(uuid.uuid4())[:8]
    conversations.setdefault(cid,[]).append({"role":"user","content":req.message,"time":now_iso()})
    lower=req.message.lower()
    if "video" in lower: reply=f"✅ Video REAL: '{req.message[:80]}' — POST /api/v1/tasks type=video"
    elif "imagen" in lower: reply=f"🎨 Imagen: '{req.message[:80]}' — POST /v1/images/generations"
    else: reply=f"Hola! Recibí '{req.message[:60]}'. Puedo: video REAL, imagen, voz, RAG, visión. ¿Qué creamos?"
    conversations[cid].append({"role":"assistant","content":reply,"time":now_iso()})
    return {"reply":reply,"conversation_id":cid,"timestamp":now_iso()}

# ========== OPENAI COMPATIBLE LLM ==========
@app.post("/v1/chat/completions")
async def openai_chat(req:OpenAIChatRequest, api_key=Depends(verify_api_key)):
    # Simula LLM - en producción conecta a OpenAI/Anthropic aquí con API_KEY
    # Si tienes OPENAI_API_KEY en env, descomenta el bloque httpx
    import os
    if os.getenv("OPENAI_API_KEY"):
        try:
            import httpx
            async with httpx.AsyncClient() as c:
                r=await c.post("https://api.openai.com/v1/chat/completions", headers={"Authorization":f"Bearer {os.getenv('OPENAI_API_KEY')}"}, json=req.model_dump(), timeout=30)
                return r.json()
        except Exception as e: pass
    # Fallback simulado inteligente
    user_msg = next((m.content for m in reversed(req.messages) if m.role=="user"), "Hola")
    # Respuesta simulada que usa el contexto
    content = f"[Arena LLM {req.model}] Respuesta a: '{user_msg[:120]}' — Puedo ayudarte con videos 20pt, imágenes, RAG, etc. (Conecta OPENAI_API_KEY para LLM real)"
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object":"chat.completion",
        "created": int(time.time()),
        "model": req.model,
        "choices":[{"index":0,"message":{"role":"assistant","content":content},"finish_reason":"stop"}],
        "usage":{"prompt_tokens": len(user_msg.split()), "completion_tokens": len(content.split()), "total_tokens": len(user_msg.split())+len(content.split())}
    }

@app.get("/v1/models")
def list_models(): return {"object":"list","data":[{"id":"arena-llm","object":"model","owned_by":"arena"},{"id":"arena-vision","object":"model"},{"id":"arena-image","object":"model"}]}

# ========== VISION ==========
@app.post("/v1/vision")
async def vision(req:VisionRequest, api_key=Depends(verify_api_key)):
    # Mock vision - en producción conecta a GPT-4V / Gemini Vision
    q=req.question or "Describe"
    return {"model":"arena-vision","question":q,"answer":f"[Visión simulada] Veo una imagen y respondo a '{q}'. Conecta tu LLM de visión para análisis real.","image_received": bool(req.image_url or req.image_base64)}

@app.post("/api/v1/ocr")
async def ocr(file: UploadFile = File(...), api_key=Depends(verify_api_key)):
    content = await file.read()
    return {"filename": file.filename, "text": f"[OCR simulado] Texto extraído de {file.filename} ({len(content)} bytes). Conecta tu OCR real aquí.", "chars": len(content)}

# ========== IMAGES ==========
@app.post("/v1/images/generations")
async def images(req:ImageGenRequest, api_key=Depends(verify_api_key)):
    # Crea tarea async y/o genera placeholder inmediato
    # Para demo, crea una tarea y devuelve mock
    task_id = str(uuid.uuid4())[:8]
    # También crea imagen placeholder sincrónica si n=1
    from PIL import Image, ImageDraw, ImageFont
    w,h = map(int, req.size.split("x")) if "x" in req.size else (1024,1024)
    img_path = DATA_DIR / f"{task_id}.jpg"
    img = Image.new('RGB', (w,h), color=(10,22,40))
    d = ImageDraw.Draw(img)
    try: font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
    except: font = ImageFont.load_default()
    d.text((40, h//2-40), textwrap.fill(req.prompt[:100], width=30), fill=(255,255,255), font=font)
    img.save(img_path)
    b64 = base64.b64encode(open(img_path,"rb").read()).decode()
    return {"created": int(time.time()), "data": [{"url": f"/api/v1/tasks/{task_id}/download", "b64_json": b64[:200]+"...", "prompt": req.prompt, "task_id": task_id}]}

# ========== AUDIO ==========
@app.post("/v1/audio/speech")
async def tts(req:TTSRequest, api_key=Depends(verify_api_key)):
    from gtts import gTTS
    tid = str(uuid.uuid4())[:8]
    out = DATA_DIR / f"{tid}.mp3"
    gTTS(text=req.text[:800], lang=req.lang, slow=False).save(str(out))
    return {"task_id": tid, "audio_url": f"/api/v1/tasks/{tid}/download", "text": req.text[:100], "voice": req.voice}

@app.post("/v1/audio/transcriptions")
async def stt(file: UploadFile = File(...), language: str = Form("es"), api_key=Depends(verify_api_key)):
    # Mock STT - en producción usa Whisper
    data = await file.read()
    return {"text": f"[Transcripción simulada] Audio {file.filename} ({len(data)} bytes) en {language}. Conecta Whisper para real.", "language": language}

# ========== RAG ==========
@app.post("/v1/knowledge/upload")
async def rag_upload(req:RAGUpload, api_key=Depends(verify_api_key)):
    kid = req.id or str(uuid.uuid4())[:8]
    knowledge_store[kid] = {"id": kid, "text": req.text, "metadata": req.metadata or {}, "created": now_iso(), "hash": hashlib.md5(req.text.encode()).hexdigest()}
    return {"id": kid, "status":"indexed", "chars": len(req.text)}

@app.post("/v1/knowledge/query")
async def rag_query(req:RAGQuery, api_key=Depends(verify_api_key)):
    # Búsqueda naive por substring
    results=[]
    for kid, doc in knowledge_store.items():
        if any(w.lower() in doc["text"].lower() for w in req.query.split()[:3]):
            results.append({"id": kid, "text": doc["text"][:300], "score": 0.9, "metadata": doc["metadata"]})
    if not results and knowledge_store:
        # devuelve 1 doc cualquiera
        kid, doc = next(iter(knowledge_store.items()))
        results=[{"id":kid,"text":doc["text"][:300],"score":0.5,"metadata":doc["metadata"]}]
    answer = f"[RAG] Respuesta a '{req.query}' basada en {len(results)} docs. " + (results[0]["text"][:150] if results else "Sin docs, sube primero con /v1/knowledge/upload")
    return {"query": req.query, "answer": answer, "sources": results[:req.top_k]}

@app.get("/v1/knowledge")
def rag_list(api_key=Depends(verify_api_key)): return {"count": len(knowledge_store), "items": list(knowledge_store.values())[:20]}

# ========== UTILS ==========
@app.post("/v1/translate")
async def translate(req:TranslateRequest, api_key=Depends(verify_api_key)):
    # Mock - en producción usa tu LLM
    return {"source": req.source, "target": req.target, "original": req.text, "translation": f"[Traducción {req.target} simulada] {req.text[:200]} (conecta LLM para real)"}

@app.post("/v1/summarize")
async def summarize(req:SummarizeRequest, api_key=Depends(verify_api_key)):
    words = req.text.split()
    summary = " ".join(words[:req.max_length]) + ("..." if len(words)>req.max_length else "")
    return {"summary": summary, "original_length": len(words), "summary_length": len(summary.split())}

@app.post("/v1/extract")
async def extract(request: Request, api_key=Depends(verify_api_key)):
    body = await request.json()
    return {"extracted": {"prompt": body.get("text","")[:100], "entities": ["Arena","Video","20pt"]}, "note":"Conecta LLM para extracción real"}

# ========== TASKS (VIDEO REAL) ==========
@app.post("/api/v1/tasks")
async def create_task(req:TaskCreate, api_key=Depends(verify_api_key)):
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
    for ext in [".mp4",".jpg",".mp3"]:
        p = DATA_DIR / f"{task_id}{ext}"
        if p.exists():
            media = "video/mp4" if ext==".mp4" else "image/jpeg" if ext==".jpg" else "audio/mpeg"
            return FileResponse(str(p), media_type=media, filename=f"{task_id}{ext}")
    return JSONResponse(t["result"])

@app.post("/api/v1/webhook/test")
async def test_webhook(request: Request):
    body = await request.json()
    import httpx
    try:
        async with httpx.AsyncClient() as c:
            r=await c.post(body["url"], json=body.get("payload") or {"test":"hola","time":now_iso()}, timeout=5)
            return {"success":True,"status":r.status_code,"response":r.text[:500]}
    except Exception as e: return {"success":False,"error":str(e)}
