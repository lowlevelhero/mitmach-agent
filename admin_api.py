import os
import logging
from flask import Blueprint, request, jsonify
from functools import wraps

logger = logging.getLogger(__name__)
admin_blueprint = Blueprint("admin", __name__)

ADMIN_KEY = os.environ.get("ADMIN_SECRET_KEY", "")

# Wird von main.py gesetzt
_scheduler = None
_run_agent = None

def set_scheduler(s):
    global _scheduler
    _scheduler = s

def set_run_agent(fn):
    global _run_agent
    _run_agent = fn

# ── Auth ───────────────────────────────────────────────
def require_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-Admin-Key")
        if not key or key != ADMIN_KEY:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

# ── Agent befehlen ─────────────────────────────────────
@admin_blueprint.post("/agent/run")
@require_key
def agent_run():
    """Schickt eine beliebige Aufgabe an den Agenten"""
    task = request.json.get("task")
    if not task:
        return jsonify({"error": "Kein Task angegeben"}), 400
    logger.info(f"Admin Task: {task[:80]}")
    result = _run_agent(task)
    return jsonify({"result": result})

# ── Code-Datei deployen ────────────────────────────────
@admin_blueprint.post("/deploy/file")
@require_key
def deploy_file():
    """Aktualisiert eine Python-Datei direkt auf dem Server"""
    filepath = request.json.get("path")
    content  = request.json.get("content")

    if not filepath or not content:
        return jsonify({"error": "path und content erforderlich"}), 400
    if not filepath.endswith(".py") or ".." in filepath or filepath.startswith("/"):
        return jsonify({"error": "Nur .py Dateien im Projektordner erlaubt"}), 400

    with open(filepath, "w") as f:
        f.write(content)

    logger.info(f"Datei deployed: {filepath}")
    return jsonify({"status": "deployed", "file": filepath})

# ── Server neu starten ─────────────────────────────────
@admin_blueprint.post("/deploy/restart")
@require_key
def restart():
    """Startet den Server neu (Replit übernimmt das automatisch)"""
    import subprocess
    logger.info("Restart angefordert")
    subprocess.Popen(["kill", "-HUP", "1"])
    return jsonify({"status": "restarting"})

# ── Scheduler steuern ──────────────────────────────────
@admin_blueprint.get("/scheduler/jobs")
@require_key
def list_jobs():
    jobs = [{"id": j.id, "next_run": str(j.next_run_time)}
            for j in _scheduler.get_jobs()]
    return jsonify({"jobs": jobs})

@admin_blueprint.post("/scheduler/pause")
@require_key
def pause():
    _scheduler.pause()
    return jsonify({"status": "paused"})

@admin_blueprint.post("/scheduler/resume")
@require_key
def resume():
    _scheduler.resume()
    return jsonify({"status": "running"})

# ── Logs ───────────────────────────────────────────────
@admin_blueprint.get("/logs")
@require_key
def get_logs():
    try:
        with open("agent.log", "r") as f:
            lines = f.readlines()
        return jsonify({"logs": lines[-50:]})
    except FileNotFoundError:
        return jsonify({"logs": []})
