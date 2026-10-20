import os
import sys
import json
import time
import asyncio
from datetime import datetime, timedelta
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import pipeline
import db_mongo

# UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

app = FastAPI(title="Gadgets Mankind Automation Cloud Service")

# Allow CORS so socialpannel can query from anywhere
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global State
automation_state = {
    "status": "RUNNING",
    "is_paused": False,
    "interval_hours": 3,
    "last_run": None,
    "next_run": (datetime.now() + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S"),
    "is_processing": False,
    "last_result": None
}

def load_recent_history():
    # 1. Primary: MongoDB Atlas (if configured)
    mongo_hist = db_mongo.load_recent_history_from_mongo(limit=10)
    if mongo_hist is not None and len(mongo_hist) > 0:
        return mongo_hist

    # 2. Fallback: Local logs file
    history_file = os.path.join(os.path.dirname(__file__), "logs", "post_history.json")
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data[-10:][::-1]
        except:
            return []
    return []

def run_cycle_task():
    global automation_state
    if automation_state["is_processing"]:
        print("[!] Cycle already in progress. Skipping.")
        return
    automation_state["is_processing"] = True
    automation_state["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        success = pipeline.execute_pipeline_cycle()
        automation_state["last_result"] = "Success" if success else "No Video / Failed"
    except Exception as e:
        print(f"[X] Error during cycle: {e}")
        automation_state["last_result"] = f"Error: {e}"
    finally:
        automation_state["is_processing"] = False
        next_dt = datetime.now() + timedelta(hours=automation_state["interval_hours"])
        automation_state["next_run"] = next_dt.strftime("%Y-%m-%d %H:%M:%S")

async def background_scheduler():
    """Background loop that runs on Render 24/7 every 3 hours"""
    print("[*] 24/7 Cloud Background Scheduler Started!")
    # Initial pause of 30 seconds on startup
    await asyncio.sleep(30)
    while True:
        if automation_state["is_paused"]:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Bot is PAUSED. Skipping scheduled 3-hour cycle.")
        else:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Triggering scheduled 3-hour cycle...")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, run_cycle_task)
            
        sleep_seconds = automation_state["interval_hours"] * 3600
        print(f"[*] Sleeping for {automation_state['interval_hours']} hours...")
        await asyncio.sleep(sleep_seconds)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(background_scheduler())

@app.get("/health")
def health():
    tracker = pipeline.telegram_extractor.load_tracker()
    history = load_recent_history()
    return {
        "status": "PAUSED" if automation_state["is_paused"] else "RUNNING",
        "is_paused": automation_state["is_paused"],
        "is_processing": automation_state["is_processing"],
        "interval_hours": automation_state["interval_hours"],
        "last_run": automation_state["last_run"],
        "next_run": automation_state["next_run"],
        "last_message_id": tracker.get("last_processed_id", 0),
        "mongodb_connected": db_mongo.is_connected(),
        "total_posts": len(history),
        "recent_posts": history[:5]
    }

@app.get("/api/status")
def api_status():
    return health()

@app.post("/pause")
def pause_bot():
    automation_state["is_paused"] = True
    automation_state["status"] = "PAUSED"
    return {"status": "success", "message": "Bot PAUSED. Scheduled runs stopped.", "is_paused": True}

@app.post("/resume")
def resume_bot():
    automation_state["is_paused"] = False
    automation_state["status"] = "RUNNING"
    return {"status": "success", "message": "Bot RESUMED. Scheduled runs active.", "is_paused": False}

@app.post("/trigger-now")
def trigger_now(background_tasks: BackgroundTasks):
    if automation_state["is_processing"]:
        return JSONResponse({"status": "error", "message": "A cycle is already running!"}, status_code=400)
    background_tasks.add_task(run_cycle_task)
    return {"status": "success", "message": "Cycle triggered in background!"}

@app.get("/", response_class=HTMLResponse)
def dashboard():
    tracker = pipeline.telegram_extractor.load_tracker()
    last_id = tracker.get("last_processed_id", 0)
    history = load_recent_history()
    is_paused = automation_state["is_paused"]

    history_html = ""
    if not history:
        history_html = "<div class='text-zinc-500 text-sm py-4'>No posts logged yet. First cycle running shortly.</div>"
    else:
        for item in history:
            ts = item.get("timestamp", "")
            mid = item.get("telegram_message_id", "")
            summary = item.get("summary", "Product clip")
            ig_link = item.get("instagram", {}).get("result", "")
            fb_id = item.get("facebook", {}).get("result", "")

            history_html += f"""
            <div class='p-3 bg-zinc-900 border border-zinc-800 rounded-lg mb-2 flex items-center justify-between text-xs'>
                <div>
                    <span class='text-white font-semibold'>Msg #{mid}</span> - <span class='text-zinc-400'>{summary}</span>
                    <div class='text-[11px] text-zinc-500 mt-0.5'>{ts}</div>
                </div>
                <div class='flex items-center space-x-2'>
                    {"<a href='" + ig_link + "' target='_blank' class='px-2 py-1 rounded bg-[#FF007A]/20 text-[#FF007A] font-medium hover:underline'>Instagram Reel</a>" if ig_link and 'instagram.com' in ig_link else "<span class='text-zinc-600'>IG -</span>"}
                    {"<span class='px-2 py-1 rounded bg-[#0066FF]/20 text-[#0066FF] font-medium'>FB #" + str(fb_id) + "</span>" if fb_id and fb_id != 'None' else "<span class='text-zinc-600'>FB -</span>"}
                </div>
            </div>
            """

    mongo_ok = db_mongo.is_connected()
    mongo_badge = """
    <span class="px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-950 text-emerald-400 border border-emerald-800 flex items-center gap-1">
        <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> MongoDB Atlas
    </span>
    """ if mongo_ok else """
    <span class="px-2 py-0.5 rounded text-[11px] font-medium bg-zinc-900 text-zinc-400 border border-zinc-800 flex items-center gap-1">
        <span class="w-1.5 h-1.5 rounded-full bg-zinc-500"></span> Cloud Sync Active
    </span>
    """

    status_badge = """
    <div class="flex items-center space-x-2">
        <span class="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse"></span>
        <span class="text-xs text-emerald-400 font-semibold">Running 24/7 (Active)</span>
    </div>
    """ if not is_paused else """
    <div class="flex items-center space-x-2">
        <span class="w-2.5 h-2.5 rounded-full bg-amber-400"></span>
        <span class="text-xs text-amber-400 font-semibold">PAUSED (Stopped)</span>
    </div>
    """

    toggle_btn = f"""
    <button onclick="toggleBot({'false' if is_paused else 'true'})" class="px-4 py-2 {'bg-emerald-500 hover:bg-emerald-400 text-black' if is_paused else 'bg-red-500 hover:bg-red-400 text-white'} font-semibold text-xs rounded-lg transition-all shadow-sm">
        {'▶️ Start / Resume Bot' if is_paused else '⏸️ Stop / Pause Bot'}
    </button>
    """

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Gadgets Mankind — 24/7 Cloud Automation</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;600;700&display=swap');
            body {{ font-family: 'Geist', -apple-system, sans-serif; }}
        </style>
    </head>
    <body class="bg-black text-zinc-200 antialiased min-h-screen p-4 md:p-8">
        <div class="max-w-4xl mx-auto space-y-6">
            
            <!-- Header -->
            <div class="border-b border-zinc-800 pb-4 flex items-center justify-between">
                <div>
                    <div class="flex items-center space-x-2">
                        <span class="text-white font-bold text-lg tracking-tight">Gadgets Mankind Automation</span>
                        <span class="text-xs px-2 py-0.5 rounded-full border border-zinc-700 bg-zinc-900 text-zinc-400">24/7 Cloud</span>
                    </div>
                    <p class="text-xs text-zinc-500">Telegram @allterapost ➔ Groq Dubbing ➔ Instagram Reels & Facebook</p>
                </div>
                <div class="flex items-center space-x-3">
                    {mongo_badge}
                    {status_badge}
                </div>
            </div>

            <!-- Stats Grid -->
            <div class="grid grid-cols-1 sm:grid-cols-4 gap-4">
                <div class="p-4 bg-zinc-950 border border-zinc-800 rounded-xl">
                    <div class="text-[11px] text-zinc-500 uppercase font-semibold">Post Cadence</div>
                    <div class="text-xl font-bold text-white mt-1">Every 3 Hours</div>
                    <div class="text-xs {'text-emerald-400' if not is_paused else 'text-amber-400'} mt-0.5">{'8 Reels / 24 hrs' if not is_paused else 'Paused'}</div>
                </div>

                <div class="p-4 bg-zinc-950 border border-zinc-800 rounded-xl">
                    <div class="text-[11px] text-zinc-500 uppercase font-semibold">Channel Source</div>
                    <div class="text-xl font-bold text-white mt-1">@allterapost</div>
                    <div class="text-xs text-zinc-400 mt-0.5">Oldest ➔ Newest</div>
                </div>

                <div class="p-4 bg-zinc-950 border border-zinc-800 rounded-xl">
                    <div class="text-[11px] text-zinc-500 uppercase font-semibold">Last Processed</div>
                    <div class="text-xl font-bold text-white mt-1">Msg #{last_id}</div>
                    <div class="text-xs text-zinc-400 mt-0.5">Auto-incrementing</div>
                </div>

                <div class="p-4 bg-zinc-950 border border-zinc-800 rounded-xl">
                    <div class="text-[11px] text-zinc-500 uppercase font-semibold">Target Account</div>
                    <div class="text-xl font-bold text-white mt-1">@gadgetsmankind</div>
                    <div class="text-xs text-zinc-400 mt-0.5">Meta Permanent Token</div>
                </div>
            </div>

            <!-- Action & Live Controls Banner -->
            <div class="p-5 bg-zinc-950 border border-zinc-800 rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                <div>
                    <div class="text-sm font-semibold text-white">Next Scheduled Post</div>
                    <div class="text-xs text-zinc-400 mt-0.5">
                        Status: <span class="{'text-emerald-400' if not is_paused else 'text-amber-400'} font-medium">{'PAUSED' if is_paused else ('Processing now...' if automation_state['is_processing'] else 'Waiting for schedule')}</span>
                        {" &bull; Next run: " + automation_state["next_run"] if (not is_paused and automation_state["next_run"]) else ""}
                    </div>
                </div>
                <div class="flex items-center space-x-3">
                    {toggle_btn}
                    <button onclick="triggerNow()" class="px-4 py-2 bg-white hover:bg-zinc-200 text-black font-semibold text-xs rounded-lg transition-all shadow-sm">
                        ⚡ Publish Next Video Now
                    </button>
                </div>
            </div>

            <!-- Recent Published Feed -->
            <div class="p-5 bg-zinc-950 border border-zinc-800 rounded-xl space-y-3">
                <div class="text-sm font-semibold text-white">Recent Publishing Activity</div>
                {history_html}
            </div>

        </div>

        <script>
            function triggerNow() {{
                if (confirm("Publish the next video from Telegram to Instagram and Facebook right now?")) {{
                    fetch('/trigger-now', {{ method: 'POST' }})
                        .then(r => r.json())
                        .then(data => {{
                            alert(data.message);
                            location.reload();
                        }})
                        .catch(e => alert("Error: " + e));
                }}
            }}

            function toggleBot(pause) {{
                const endpoint = pause ? '/pause' : '/resume';
                const actionName = pause ? 'STOP / PAUSE' : 'START / RESUME';
                if (confirm("Are you sure you want to " + actionName + " the automated 3-hour scheduler?")) {{
                    fetch(endpoint, {{ method: 'POST' }})
                        .then(r => r.json())
                        .then(data => {{
                            alert(data.message);
                            location.reload();
                        }})
                        .catch(e => alert("Error: " + e));
                }}
            }}

            // Auto refresh status every 60s
            setTimeout(() => location.reload(), 60000);
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
