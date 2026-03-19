import anthropic
import requests
import json
import logging
import os
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from admin_api import admin_blueprint, set_scheduler, set_run_agent

# ── Logging ───────────────────────────────────────────
logging.basicConfig(
    filename="agent.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

PLATFORM_URL   = os.environ.get("PLATFORM_URL", "https://mitmachplattform.de")
AGENT_TOKEN    = os.environ.get("AGENT_TOKEN", "")
platform_headers = {"x-agent-token": AGENT_TOKEN}

# ── Tools: Was der Agent tun darf ─────────────────────
tools = [
    {
        "name": "get_new_applications",
        "description": "Holt alle neuen Bewerbungen der letzten 24 Stunden",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "get_inactive_companies",
        "description": "Holt Betriebe die seit X Tagen nicht auf Bewerbungen reagiert haben",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Anzahl Tage ohne Reaktion"}
            },
            "required": ["days"]
        }
    },
    {
        "name": "send_reminder_email",
        "description": "Sendet eine Erinnerungsmail an einen Betrieb",
        "input_schema": {
            "type": "object",
            "properties": {
                "company_id": {"type": "integer"},
                "reason": {"type": "string"}
            },
            "required": ["company_id", "reason"]
        }
    },
    {
        "name": "get_platform_stats",
        "description": "Holt aktuelle Statistiken der Plattform (Betriebe, Stellen, Bewerbungen)",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "notify_ferdinand",
        "description": "Sendet Ferdinand eine wichtige Benachrichtigung per E-Mail",
        "input_schema": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "priority": {"type": "string", "enum": ["low", "medium", "high"]}
            },
            "required": ["message", "priority"]
        }
    }
]

# ── Tool Ausführung ────────────────────────────────────
def execute_tool(name, tool_input):
    logger.info(f"Tool: {name} | Input: {tool_input}")
    try:
        if name == "get_new_applications":
            r = requests.get(f"{PLATFORM_URL}/api/admin/applications?new=true", headers=platform_headers, timeout=10)
            return r.json()

        elif name == "get_inactive_companies":
            days = tool_input.get("days", 7)
            r = requests.get(f"{PLATFORM_URL}/api/admin/companies?inactive_days={days}", headers=platform_headers, timeout=10)
            return r.json()

        elif name == "send_reminder_email":
            r = requests.post(f"{PLATFORM_URL}/api/admin/emails/reminder",
                headers=platform_headers,
                json={"company_id": tool_input["company_id"], "reason": tool_input["reason"]},
                timeout=10)
            return r.json()

        elif name == "get_platform_stats":
            r = requests.get(f"{PLATFORM_URL}/api/admin/stats", headers=platform_headers, timeout=10)
            return r.json()

        elif name == "notify_ferdinand":
            r = requests.post(f"{PLATFORM_URL}/api/admin/notify",
                headers=platform_headers,
                json=tool_input,
                timeout=10)
            return {"sent": True}

    except Exception as e:
        logger.error(f"Tool {name} Fehler: {e}")
        return {"error": str(e)}

    return {"error": f"Unbekanntes Tool: {name}"}

# ── Agent Loop ─────────────────────────────────────────
def run_agent(task: str) -> str:
    logger.info(f"Agent Task: {task[:100]}")
    messages = [{"role": "user", "content": task}]

    system = """Du bist der virtuelle Mitarbeiter der Mitmachplattform (mitmachplattform.de).
Du verbindest Handwerksbetriebe mit Azubis im Raum Konstanz.
Du arbeitest selbstständig, triffst sinnvolle Entscheidungen und
benachrichtigst Ferdinand nur bei wirklich wichtigen Dingen.
Sei proaktiv, präzise und halte Antworten kurz."""

    while True:
        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=2048,
            system=system,
            tools=tools,
            messages=messages
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    logger.info(f"Agent fertig: {block.text[:100]}")
                    return block.text
            return "Aufgabe erledigt."

        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result)
                    })
            messages.append({"role": "user", "content": tool_results})

# ── Geplante Aufgaben ──────────────────────────────────
def daily_check():
    logger.info("Täglicher Check gestartet")
    run_agent("""
        Führe den täglichen Morgen-Check durch:
        1. Prüfe neue Bewerbungen — haben alle Betriebe reagiert?
        2. Erinnere Betriebe die seit 7+ Tagen nicht reagiert haben
        3. Benachrichtige Ferdinand nur wenn etwas Wichtiges passiert ist
    """)

def weekly_report():
    logger.info("Wochenbericht gestartet")
    run_agent("""
        Erstelle den Wochenbericht:
        1. Hole aktuelle Plattform-Statistiken
        2. Analysiere was gut lief und was nicht
        3. Schicke Ferdinand eine Zusammenfassung mit Top 3 Prioritäten
    """)

scheduler = BackgroundScheduler()
scheduler.add_job(daily_check,   "cron", hour=8,  minute=0)
scheduler.add_job(weekly_report, "cron", day_of_week="mon", hour=7)
scheduler.start()

# Admin Blueprint einbinden
set_scheduler(scheduler)
set_run_agent(run_agent)
app.register_blueprint(admin_blueprint, url_prefix="/admin")

# ── Health Check ───────────────────────────────────────
@app.get("/health")
def health():
    return jsonify({"status": "online", "agent": "Mitmachplattform Mitarbeiter"})

if __name__ == "__main__":
    logger.info("Agent Server gestartet")
    app.run(host="0.0.0.0", port=8080)
