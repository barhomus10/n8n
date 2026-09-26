# Arena Agent API — Despliegue Permanente

API lista en `/home/user/task_api/app.py` — ya corre en sandbox: `https://8000-i4eknp8s4unwgwrvh3a29.e2b.app`

Para URL fija tipo `https://tu-api.onrender.com` haz uno de estos (2 min):

## Opción A — Render (1-click, recomendado gratis)

1. **Sube a GitHub:**
```bash
cd /home/user/task_api
git init
git add .
git commit -m "Arena Agent API"
# Crea repo vacío en github.com (ej: tu-usuario/arena-agent-api)
git remote add origin https://github.com/TU-USUARIO/arena-agent-api.git
git branch -M main
git push -u origin main
```

2. **En Render.com:**
- Dashboard → New + → Blueprint → conecta tu repo → Render detecta `render.yaml` automáticamente
- O New + → Web Service → conecta repo → Environment: Docker → Build Command: vacío (usa Dockerfile) → Start Command: `uvicorn app:app --host 0.0.0.0 --port $PORT --workers 2`
- Añade ENV `API_KEY=arena-demo-key-2025` (cámbiala)
- Deploy → te da URL fija `https://arena-agent-api.onrender.com`

**Botón 1-click (después de subir a GitHub):**
```
https://render.com/deploy?repo=https://github.com/TU-USUARIO/arena-agent-api
```

## Opción B — Railway (aún más rápido)
1. https://railway.app → New Project → Deploy from GitHub repo
2. Railway detecta Dockerfile → Deploy → te da `https://arena-agent-api.up.railway.app`
3. Variables → `API_KEY=...`

## Opción C — Fly.io
```bash
curl -L https://fly.io/install.sh | sh
fly launch   # elige nombre: tu-api
fly deploy
fly open
```

## Opción D — Hugging Face Spaces (gratis, Docker)
1. Crea Space → Docker → sube estos archivos
2. Te da `https://TU-USUARIO-arena-agent-api.hf.space`

## Probar URL fija
```bash
curl https://tu-api.onrender.com/health
curl -X POST https://tu-api.onrender.com/api/v1/chat -H "Content-Type: application/json" -d '{"message":"Hola"}'
curl -X POST https://tu-api.onrender.com/api/v1/tasks -H "X-API-Key: arena-demo-key-2025" -H "Content-Type: application/json" -d '{"type":"video","prompt":"Video 20pt palabra por palabra con música baja"}'
```

## Conexión real a generación de video
En `app.py` función `execute_task()` cambia el `asyncio.sleep` por tu pipeline real:
```python
# Ejemplo: llamar a tu generador de video 20pt + música
from generar_video import crear_video
result_path = crear_video(task["prompt"], task["options"])
task["result"] = {"download_url": f"/files/{result_path}"}
```
Ya tienes el pipeline en `/home/user/video_generosidad/generar_musica.py` y `generar_srt_palabra.py` — solo importarlo.

## Archivos incluidos
- `app.py` → API FastAPI
- `Dockerfile` → deploy Docker
- `render.yaml` → blueprint Render
- `requirements.txt`

¿Quieres que lo suba yo ahora? Pásame:
- Tu usuario de GitHub + si quieres que cree el repo
- O tu API Key de Render/Railway y lo despliego directo
