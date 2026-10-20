import os
import sys
import json
import time
import asyncio
import urllib.parse
from datetime import datetime, timedelta
from fastapi import FastAPI, BackgroundTasks, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

import log_streamer
log_streamer.init_log_streamer()

import pipeline
import db_mongo
import auto_dm
import affiliate_manager
import config_loader

# UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

app = FastAPI(title="Gadgets Mankind Automation Cloud Service")

# Mount static directory for thumbnails and assets
static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(os.path.join(static_dir, "thumbnails"), exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

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
    "next_run_iso": (datetime.now() + timedelta(hours=3)).isoformat(),
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
        automation_state["next_run_iso"] = next_dt.isoformat()

async def background_scheduler():
    """Background loop that runs on Render 24/7 every 3 hours"""
    print("[*] 24/7 Cloud Background Scheduler Started!")
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

async def background_autodm_scanner():
    """Background loop that scans recent Reels for comments every 3 minutes to send Amazon Auto-DMs"""
    print("[*] Auto-DM Comment Scanner Loop active!")
    await asyncio.sleep(45)
    while True:
        try:
            cfg = config_loader.load_config()
            loop = asyncio.get_event_loop()
            replied = await loop.run_in_executor(None, auto_dm.scan_and_reply_recent_comments, cfg)
            if replied > 0:
                print(f"[📩] Auto-DM Scanner: Delivered {replied} Amazon affiliate link(s) to commenters!")
        except Exception as e:
            pass
        await asyncio.sleep(180)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(background_scheduler())
    asyncio.create_task(background_autodm_scanner())

# ==============================================================
# META INSTAGRAM WEBHOOKS (REAL-TIME AUTO-DM)
# ==============================================================

@app.get("/webhook")
def meta_webhook_verification(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")
    expected_token = os.environ.get("META_VERIFY_TOKEN", "gadgets_mankind_autodm_secret_token_2026")

    if mode == "subscribe" and token == expected_token:
        print("[+] Meta Webhook verified successfully!")
        return int(challenge) if challenge and challenge.isdigit() else challenge
    return JSONResponse({"error": "Forbidden - Token Mismatch"}, status_code=403)

@app.post("/webhook")
async def meta_webhook_receiver(request: Request):
    try:
        data = await request.json()
        cfg = config_loader.load_config()
        handled = auto_dm.handle_webhook_event(data, cfg)
        return {"status": "ok", "comments_processed": handled}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# ==============================================================
# SMART DEEP LINK APP OPENER (BYPASSES IN-APP BROWSER)
# ==============================================================

@app.get("/open", response_class=HTMLResponse)
def open_in_amazon_app(q: str = "gadgets", tag: str = None):
    amazon_tag = tag or affiliate_manager.get_amazon_tag()
    clean_q = affiliate_manager.clean_search_term(q)
    encoded_q = urllib.parse.quote_plus(clean_q)
    web_fallback = f"https://www.amazon.in/s?k={encoded_q}&tag={amazon_tag}"
    
    # Android Intent: forces Android to bypass Instagram webview and launch native Amazon App
    android_intent = (
        f"intent://www.amazon.in/s?k={encoded_q}&tag={amazon_tag}"
        f"#Intent;scheme=https;package=in.amazon.mShop.android.shopping;"
        f"S.browser_fallback_url={urllib.parse.quote_plus(web_fallback)};end"
    )
    # iOS Universal / Custom Deep Link
    ios_deeplink = f"com.amazon.mobile.shopping://www.amazon.in/s?k={encoded_q}&tag={amazon_tag}"

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Opening Amazon App • {clean_q.title()}</title>
    <link rel="icon" href="https://www.amazon.in/favicon.ico">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @keyframes pulse-ring {{
            0% {{ transform: scale(0.95); opacity: 0.8; }}
            50% {{ transform: scale(1.05); opacity: 0.3; }}
            100% {{ transform: scale(0.95); opacity: 0.8; }}
        }}
        .animate-ring {{
            animation: pulse-ring 2s infinite ease-in-out;
        }}
    </style>
</head>
<body class="bg-[#0f1115] text-zinc-100 min-h-screen flex items-center justify-center p-4 antialiased font-sans">
    <div class="max-w-md w-full bg-zinc-900/90 border border-zinc-800 rounded-3xl p-6 shadow-2xl backdrop-blur-xl text-center flex flex-col items-center">
        <!-- Amazon Header Badge -->
        <div class="relative mb-5 flex items-center justify-center">
            <div class="absolute inset-0 bg-[#FF9900]/20 rounded-full blur-xl animate-ring"></div>
            <div class="relative w-16 h-16 bg-[#131921] border border-zinc-700/80 rounded-2xl flex items-center justify-center shadow-lg">
                <svg class="w-10 h-10 fill-[#FF9900]" viewBox="0 0 24 24">
                    <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-1 15.5c-3.03 0-5.5-2.47-5.5-5.5S7.97 6.5 11 6.5s5.5 2.47 5.5 5.5-2.47 5.5-5.5 5.5zm6.85-2.15l-1.42 1.42c-.2.2-.51.2-.71 0l-1.06-1.06c-.2-.2-.2-.51 0-.71l1.42-1.42c.2-.2.51-.2.71 0l1.06 1.06c.2.2.2.51 0 .71z"/>
                </svg>
            </div>
        </div>

        <span class="text-xs uppercase font-bold tracking-widest text-[#FF9900] bg-[#FF9900]/10 px-3 py-1 rounded-full border border-[#FF9900]/20 mb-3">
            Amazon Direct App Opener
        </span>

        <h1 class="text-xl font-bold text-white mb-2 leading-snug line-clamp-2">
            {clean_q.title()}
        </h1>

        <p class="text-xs text-zinc-400 mb-6 flex items-center justify-center gap-2">
            <svg class="animate-spin h-3.5 w-3.5 text-[#FF9900]" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
            </svg>
            Redirecting to native Amazon app...
        </p>

        <!-- Primary Action Button: Opens Amazon App -->
        <a id="btn-open-app" href="{android_intent}" class="w-full bg-gradient-to-r from-[#FF9900] to-[#E68A00] hover:from-[#e58a00] hover:to-[#cc7a00] text-zinc-950 font-bold py-3.5 px-6 rounded-2xl shadow-lg shadow-[#FF9900]/25 transition-all transform active:scale-95 flex items-center justify-center gap-2 mb-3 text-sm">
            <span>🛍️</span>
            <span>Open in Amazon App</span>
        </a>

        <!-- Fallback Web Browser Button -->
        <a id="btn-open-web" href="{web_fallback}" class="w-full bg-zinc-800/80 hover:bg-zinc-800 text-zinc-300 font-semibold py-3 px-6 rounded-2xl border border-zinc-700/60 transition-all text-xs flex items-center justify-center gap-2">
            <span>🌐</span>
            <span>Continue in Web Browser</span>
        </a>

        <div class="mt-6 pt-4 border-t border-zinc-800/60 w-full flex items-center justify-between text-[11px] text-zinc-500">
            <span>Verified Affiliate: <strong class="text-zinc-400">{amazon_tag}</strong></span>
            <span>100% Secure Checkout</span>
        </div>
    </div>

    <script>
        const isAndroid = /Android/i.test(navigator.userAgent);
        const isIOS = /iPhone|iPad|iPod/i.test(navigator.userAgent);
        const androidIntent = "{android_intent}";
        const iosDeeplink = "{ios_deeplink}";
        const webFallback = "{web_fallback}";

        const btnApp = document.getElementById("btn-open-app");
        if (isIOS) {{
            btnApp.href = iosDeeplink;
        }} else if (isAndroid) {{
            btnApp.href = androidIntent;
        }} else {{
            btnApp.href = webFallback;
        }}

        function autoLaunch() {{
            if (isAndroid) {{
                window.location.href = androidIntent;
            }} else if (isIOS) {{
                window.location.href = iosDeeplink;
                setTimeout(function() {{
                    window.location.href = webFallback;
                }}, 1800);
            }} else {{
                window.location.replace(webFallback);
            }}
        }}

        // Automatically fire app opener on mobile load
        window.addEventListener("DOMContentLoaded", function() {{
            setTimeout(autoLaunch, 150);
        }});
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_content)

# ==============================================================
# MONITORING & API ENDPOINTS
# ==============================================================

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
        "next_run_iso": automation_state["next_run_iso"],
        "last_message_id": tracker.get("last_processed_id", 0),
        "mongodb_connected": db_mongo.is_connected(),
        "amazon_tag": affiliate_manager.get_amazon_tag(),
        "autodm_sent_count": auto_dm.get_autodm_stats(),
        "total_posts": len(history),
        "recent_posts": history[:5]
    }

@app.get("/api/status")
def api_status():
    return health()

@app.get("/api/logs")
def api_logs(limit: int = 80):
    return {"logs": log_streamer.get_logs(limit=limit)}

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

# ==============================================================
# INTERACTIVE MASTER DASHBOARD WITH COUNTDOWN & LIVE TERMINAL
# ==============================================================

@app.get("/", response_class=HTMLResponse)
def dashboard():
    tracker = pipeline.telegram_extractor.load_tracker()
    last_id = tracker.get("last_processed_id", 0)
    history = load_recent_history()
    is_paused = automation_state["is_paused"]
    autodm_count = auto_dm.get_autodm_stats()
    amazon_tag = affiliate_manager.get_amazon_tag()
    mongo_ok = db_mongo.is_connected()

    history_html = ""
    if not history:
        history_html = "<div class='text-zinc-500 text-sm py-4'>No posts logged yet. First cycle running shortly.</div>"
    else:
        for item in history:
            ts = item.get("timestamp", "")
            mid = item.get("telegram_message_id", "")
            summary = item.get("product_name") or item.get("summary", "Product clip")
            ig_link = item.get("instagram", {}).get("result", "")
            fb_id = item.get("facebook", {}).get("result", "")
            amz_link = item.get("amazon_link", f"https://www.amazon.in/s?k=gadgets&tag={amazon_tag}")

            history_html += f"""
            <div class='p-3 bg-zinc-900/80 border border-zinc-800 rounded-lg mb-2 flex flex-col sm:flex-row sm:items-center justify-between text-xs gap-2'>
                <div>
                    <span class='text-white font-semibold'>Msg #{mid}</span> - <span class='text-zinc-300'>{summary}</span>
                    <div class='text-[11px] text-zinc-500 mt-0.5'>{ts}</div>
                </div>
                <div class='flex items-center space-x-2 flex-wrap gap-1'>
                    <a href='{amz_link}' target='_blank' class='px-2 py-1 rounded bg-[#FF9900]/20 text-[#FF9900] font-medium hover:underline flex items-center gap-1'>
                        🛒 Amazon ({amazon_tag})
                    </a>
                    {"<a href='" + ig_link + "' target='_blank' class='px-2 py-1 rounded bg-[#FF007A]/20 text-[#FF007A] font-medium hover:underline'>Instagram Reel</a>" if ig_link and 'instagram.com' in ig_link else "<span class='text-zinc-600'>IG -</span>"}
                    {"<span class='px-2 py-1 rounded bg-[#0066FF]/20 text-[#0066FF] font-medium'>FB #" + str(fb_id) + "</span>" if fb_id and fb_id != 'None' else "<span class='text-zinc-600'>FB -</span>"}
                </div>
            </div>
            """

    mongo_badge = """
    <span class="px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-950 text-emerald-400 border border-emerald-800 flex items-center gap-1">
        <span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> MongoDB Atlas
    </span>
    """ if mongo_ok else """
    <span class="px-2 py-0.5 rounded text-[11px] font-medium bg-zinc-900 text-zinc-400 border border-zinc-800 flex items-center gap-1">
        <span class="w-1.5 h-1.5 rounded-full bg-zinc-500"></span> Telegram Cloud Sync Active
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
        <title>Gadgets Mankind — 24/7 Cloud Automation & Auto-DM</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
            body {{ font-family: 'Geist', -apple-system, sans-serif; }}
            .terminal-font {{ font-family: 'JetBrains Mono', monospace; }}
            ::-webkit-scrollbar {{ width: 6px; height: 6px; }}
            ::-webkit-scrollbar-track {{ background: #09090b; }}
            ::-webkit-scrollbar-thumb {{ background: #27272a; border-radius: 3px; }}
        </style>
    </head>
    <body class="bg-black text-zinc-200 antialiased min-h-screen p-4 md:p-8">
        <div class="max-w-5xl mx-auto space-y-6">
            
            <!-- Header -->
            <div class="border-b border-zinc-800 pb-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div>
                    <div class="flex items-center space-x-2">
                        <span class="text-white font-bold text-lg tracking-tight">Gadgets Mankind Automation</span>
                        <span class="text-xs px-2 py-0.5 rounded-full border border-zinc-700 bg-zinc-900 text-zinc-400">24/7 Cloud Engine</span>
                    </div>
                    <p class="text-xs text-zinc-500">Telegram @allterapost ➔ Groq AI Dubbing ➔ Instagram Reels & Auto-DM</p>
                </div>
                <div class="flex items-center space-x-3">
                    {mongo_badge}
                    {status_badge}
                </div>
            </div>

            <!-- COUNTDOWN TIMER & CONTROLS HERO -->
            <div class="p-6 bg-gradient-to-r from-zinc-950 via-zinc-900 to-zinc-950 border border-zinc-800 rounded-2xl flex flex-col md:flex-row md:items-center justify-between gap-6 shadow-xl">
                <div>
                    <div class="text-xs uppercase tracking-wider text-zinc-400 font-semibold flex items-center gap-2">
                        <span class="w-2 h-2 rounded-full bg-indigo-500 animate-ping"></span>
                        Next Scheduled Reel Publication In
                    </div>
                    <div class="text-3xl md:text-4xl font-extrabold text-white mt-2 tracking-tight flex items-baseline gap-2">
                        <span id="countdown-timer" class="font-mono text-indigo-400">--:--:--</span>
                        <span class="text-xs text-zinc-500 font-normal">({"Paused" if is_paused else "Target: " + automation_state["next_run"]})</span>
                    </div>
                    <div class="text-xs text-zinc-400 mt-1">
                        Status: <span class="{'text-emerald-400' if not is_paused else 'text-amber-400'} font-medium">{'PAUSED' if is_paused else ('Processing live reel now...' if automation_state['is_processing'] else 'Counting down to next publication cycle')}</span>
                    </div>
                </div>
                <div class="flex items-center space-x-3">
                    {toggle_btn}
                    <button onclick="triggerNow()" class="px-4 py-2 bg-white hover:bg-zinc-200 text-black font-semibold text-xs rounded-lg transition-all shadow-sm">
                        ⚡ Publish Next Video Now
                    </button>
                </div>
            </div>

            <!-- Stats & Affiliate Metrics Grid -->
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-4">
                <div class="p-4 bg-zinc-950 border border-zinc-800 rounded-xl">
                    <div class="text-[11px] text-zinc-500 uppercase font-semibold">Post Cadence</div>
                    <div class="text-xl font-bold text-white mt-1">Every 3 Hours</div>
                    <div class="text-xs {'text-emerald-400' if not is_paused else 'text-amber-400'} mt-0.5">{'8 Reels / 24h' if not is_paused else 'Paused'}</div>
                </div>

                <div class="p-4 bg-zinc-950 border border-zinc-800 rounded-xl">
                    <div class="text-[11px] text-zinc-500 uppercase font-semibold">Amazon Affiliate Tag</div>
                    <div class="text-xl font-bold text-[#FF9900] mt-1">{amazon_tag}</div>
                    <div class="text-xs text-zinc-400 mt-0.5">Active on Amazon.in</div>
                </div>

                <div class="p-4 bg-zinc-950 border border-zinc-800 rounded-xl">
                    <div class="text-[11px] text-zinc-500 uppercase font-semibold">Auto-DMs Delivered</div>
                    <div class="text-xl font-bold text-pink-500 mt-1" id="autodm-count">{autodm_count}</div>
                    <div class="text-xs text-zinc-400 mt-0.5">Comment-to-DM active</div>
                </div>

                <div class="p-4 bg-zinc-950 border border-zinc-800 rounded-xl">
                    <div class="text-[11px] text-zinc-500 uppercase font-semibold">Last Processed</div>
                    <div class="text-xl font-bold text-white mt-1">Msg #{last_id}</div>
                    <div class="text-xs text-zinc-400 mt-0.5">Channel: @allterapost</div>
                </div>
            </div>

            <!-- LIVE TERMINAL CONSOLE -->
            <div class="bg-zinc-950 border border-zinc-800 rounded-xl overflow-hidden shadow-2xl">
                <div class="bg-zinc-900/90 px-4 py-2.5 border-b border-zinc-800 flex items-center justify-between">
                    <div class="flex items-center space-x-2">
                        <span class="w-3 h-3 rounded-full bg-red-500/80 inline-block"></span>
                        <span class="w-3 h-3 rounded-full bg-amber-500/80 inline-block"></span>
                        <span class="w-3 h-3 rounded-full bg-emerald-500/80 inline-block"></span>
                        <span class="text-xs text-zinc-400 font-medium ml-2 terminal-font">bash — gadgets-mankind-bot.log</span>
                    </div>
                    <div class="flex items-center space-x-2 text-[11px] text-zinc-500">
                        <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
                        <span>Live Output Streaming</span>
                    </div>
                </div>
                <div id="terminal-window" class="p-4 terminal-font text-xs text-emerald-400 bg-black/90 h-64 overflow-y-auto space-y-1">
                    <div class="text-zinc-500">[System] Initializing live terminal stream...</div>
                </div>
            </div>

            <!-- Recent Published Feed -->
            <div class="p-5 bg-zinc-950 border border-zinc-800 rounded-xl space-y-3">
                <div class="text-sm font-semibold text-white flex items-center justify-between">
                    <span>Recent Published Activity & Amazon Links</span>
                    <span class="text-xs text-zinc-500 font-normal">Last 10 cycles</span>
                </div>
                {history_html}
            </div>

        </div>

        <script>
            // Live Countdown Calculation
            const nextRunTarget = new Date("{automation_state['next_run']}").getTime();
            const isPaused = {'true' if is_paused else 'false'};

            function updateCountdown() {{
                if (isPaused) {{
                    document.getElementById('countdown-timer').innerText = "PAUSED";
                    return;
                }}
                const now = new Date().getTime();
                const distance = nextRunTarget - now;

                if (distance <= 0) {{
                    document.getElementById('countdown-timer').innerText = "RUNNING CYCLE...";
                    return;
                }}

                const hours = Math.floor(distance / (1000 * 60 * 60));
                const minutes = Math.floor((distance % (1000 * 60 * 60)) / (1000 * 60));
                const seconds = Math.floor((distance % (1000 * 60)) / 1000);

                const pad = (n) => String(n).padStart(2, '0');
                document.getElementById('countdown-timer').innerText = `${{pad(hours)}}h : ${{pad(minutes)}}m : ${{pad(seconds)}}s`;
            }}

            setInterval(updateCountdown, 1000);
            updateCountdown();

            // Live Terminal Streaming
            function fetchLogs() {{
                fetch('/api/logs?limit=80')
                    .then(r => r.json())
                    .then(data => {{
                        if (data && data.logs) {{
                            const term = document.getElementById('terminal-window');
                            const wasScrolledBottom = term.scrollHeight - term.clientHeight <= term.scrollTop + 50;
                            
                            term.innerHTML = data.logs.map(line => {{
                                let colorClass = 'text-zinc-300';
                                if (line.includes('[+]') || line.includes('[🍃]') || line.includes('[📩]')) colorClass = 'text-emerald-400';
                                else if (line.includes('[*]') || line.includes('[🧹]') || line.includes('[🏷️]')) colorClass = 'text-cyan-400';
                                else if (line.includes('[!]')) colorClass = 'text-amber-400';
                                else if (line.includes('[X]') || line.includes('Error')) colorClass = 'text-rose-400';
                                return `<div class="${{colorClass}}">${{line}}</div>`;
                            }}).join('') + '<div class="text-zinc-600 animate-pulse">_</div>';

                            if (wasScrolledBottom) {{
                                term.scrollTop = term.scrollHeight;
                            }}
                        }}
                    }})
                    .catch(e => console.error("Log fetch glitch", e));
            }}

            setInterval(fetchLogs, 2500);
            fetchLogs();

            function triggerNow() {{
                if (confirm("Publish the next video from Telegram to Instagram and Facebook right now?")) {{
                    fetch('/trigger-now', {{ method: 'POST' }})
                        .then(r => r.json())
                        .then(data => {{
                            alert(data.message);
                            fetchLogs();
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
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
