"""
EchoEar Server - WebSocket-based implementation
Uses websockets library for WebSocket connections (xiaozhi-compatible)
Uses FastAPI for HTTP admin endpoints
"""
import asyncio
import json
import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from .config import settings
from .registry import registry
from .ws_server import start_websocket_server

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI()

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
OPENAI_CFG_PATH = os.path.join(DATA_DIR, "openai.json")

@app.on_event("startup")
async def load_openai_config():
    """Load OpenAI configuration from disk"""
    if os.path.exists(OPENAI_CFG_PATH):
        try:
            with open(OPENAI_CFG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            settings.openai_base_url = data.get("openai_base_url", settings.openai_base_url)
            settings.openai_chat_model = data.get("openai_chat_model", settings.openai_chat_model)
            settings.openai_tts_model = data.get("openai_tts_model", settings.openai_tts_model)
            settings.openai_tts_voice = data.get("openai_tts_voice", settings.openai_tts_voice)
            logger.info("Loaded OpenAI config from disk")
        except Exception as e:
            logger.warning(f"Failed to load OpenAI config: {e}")

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {"ok": True}

@app.post("/register")
async def register_device(payload: dict):
    """Register a new device (legacy endpoint)"""
    device_id = payload.get("device_id")
    token = payload.get("token")
    if not device_id or not token:
        raise HTTPException(status_code=400, detail="device_id and token required")
    registry.register(device_id, token)
    logger.info(f"Registered device: {device_id}")
    return {"ok": True}

@app.get("/ota/")
async def ota(request):
    """Return OTA configuration for devices"""
    host = request.headers.get("host", f"{settings.ws_host}:{settings.ws_port}")
    return {
        "websocket": {
            "url": f"ws://{host}/ws",
            "version": 3
        }
    }

@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """Admin web interface"""
    return """
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>EchoEar Admin</title>
    <style>
      body { font-family: sans-serif; max-width: 760px; margin: 24px auto; padding: 0 16px; }
      h2 { margin-top: 24px; }
      table { border-collapse: collapse; width: 100%; }
      th, td { border: 1px solid #ddd; padding: 6px 8px; text-align: left; }
      input { padding: 6px; margin: 4px 0; width: 100%; }
      button { padding: 6px 10px; margin-top: 6px; }
      .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
      .danger { background: #b30000; color: white; border: none; }
    </style>
  </head>
  <body>
    <h1>EchoEar Admin</h1>

    <h2>Devices</h2>
    <div class="row">
      <div>
        <label>Device ID</label>
        <input id="device_id" placeholder="echoear-001" />
      </div>
      <div>
        <label>Token</label>
        <input id="device_token" placeholder="devtoken" />
      </div>
    </div>
    <button onclick="addDevice()">Add/Update</button>

    <table id="device_table">
      <thead><tr><th>Device ID</th><th>Token</th><th>Action</th></tr></thead>
      <tbody></tbody>
    </table>

    <h2>OpenAI Config</h2>
    <label>Base URL</label>
    <input id="openai_base_url" />
    <label>Chat Model</label>
    <input id="openai_chat_model" />
    <label>TTS Model</label>
    <input id="openai_tts_model" />
    <label>TTS Voice</label>
    <input id="openai_tts_voice" />
    <button onclick="saveOpenai()">Save OpenAI Config</button>

    <script>
      async function loadDevices() {
        const res = await fetch('/admin/devices');
        const data = await res.json();
        const tbody = document.querySelector('#device_table tbody');
        tbody.innerHTML = '';
        Object.entries(data.devices).forEach(([id, token]) => {
          const tr = document.createElement('tr');
          tr.innerHTML = `<td>${id}</td><td>${token}</td>
            <td><button class="danger" onclick="delDevice('${id}')">Delete</button></td>`;
          tbody.appendChild(tr);
        });
      }

      async function addDevice() {
        const device_id = document.getElementById('device_id').value.trim();
        const token = document.getElementById('device_token').value.trim();
        if (!device_id || !token) return alert('device_id/token required');
        await fetch('/admin/devices', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({device_id, token})
        });
        await loadDevices();
      }

      async function delDevice(id) {
        await fetch('/admin/devices/' + encodeURIComponent(id), {method: 'DELETE'});
        await loadDevices();
      }

      async function loadOpenai() {
        const res = await fetch('/admin/openai');
        const data = await res.json();
        document.getElementById('openai_base_url').value = data.openai_base_url || '';
        document.getElementById('openai_chat_model').value = data.openai_chat_model || '';
        document.getElementById('openai_tts_model').value = data.openai_tts_model || '';
        document.getElementById('openai_tts_voice').value = data.openai_tts_voice || '';
      }

      async function saveOpenai() {
        const openai_base_url = document.getElementById('openai_base_url').value.trim();
        const openai_chat_model = document.getElementById('openai_chat_model').value.trim();
        const openai_tts_model = document.getElementById('openai_tts_model').value.trim();
        const openai_tts_voice = document.getElementById('openai_tts_voice').value.trim();
        await fetch('/admin/openai', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({openai_base_url, openai_chat_model, openai_tts_model, openai_tts_voice})
        });
        alert('Saved');
      }

      loadDevices();
      loadOpenai();
    </script>
  </body>
</html>
"""

@app.get("/admin/devices")
async def admin_list_devices():
    """List all registered devices"""
    return {"devices": registry.list_devices()}

@app.post("/admin/devices")
async def admin_add_device(payload: dict):
    """Add or update a device"""
    device_id = payload.get("device_id")
    token = payload.get("token")
    if not device_id or not token:
        raise HTTPException(status_code=400, detail="device_id and token required")
    registry.register(device_id, token)
    logger.info(f"Admin registered device: {device_id}")
    return {"ok": True}

@app.delete("/admin/devices/{device_id}")
async def admin_delete_device(device_id: str):
    """Delete a device"""
    if not registry.delete(device_id):
        raise HTTPException(status_code=404, detail="device_id not found")
    logger.info(f"Admin deleted device: {device_id}")
    return {"ok": True}

@app.get("/admin/openai")
async def admin_get_openai():
    """Get OpenAI configuration"""
    return {
        "openai_base_url": settings.openai_base_url,
        "openai_chat_model": settings.openai_chat_model,
        "openai_tts_model": settings.openai_tts_model,
        "openai_tts_voice": settings.openai_tts_voice,
    }

@app.post("/admin/openai")
async def admin_set_openai(payload: dict):
    """Update OpenAI configuration"""
    settings.openai_base_url = payload.get("openai_base_url", settings.openai_base_url)
    settings.openai_chat_model = payload.get("openai_chat_model", settings.openai_chat_model)
    settings.openai_tts_model = payload.get("openai_tts_model", settings.openai_tts_model)
    settings.openai_tts_voice = payload.get("openai_tts_voice", settings.openai_tts_voice)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OPENAI_CFG_PATH, "w", encoding="utf-8") as f:
        json.dump({
            "openai_base_url": settings.openai_base_url,
            "openai_chat_model": settings.openai_chat_model,
            "openai_tts_model": settings.openai_tts_model,
            "openai_tts_voice": settings.openai_tts_voice,
        }, f, ensure_ascii=False, indent=2)
    logger.info("Updated OpenAI config")
    return {"ok": True}
