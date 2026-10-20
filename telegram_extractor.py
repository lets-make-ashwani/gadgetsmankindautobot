import os
import sys
import json
import asyncio
import re
import requests
from telethon import TelegramClient
from telethon.sessions import StringSession
import db_mongo

# UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TRACKER_FILE = os.path.join(os.path.dirname(__file__), "tracker.json")

def load_tracker():
    # 1. Primary Source of Truth: MongoDB Atlas (if configured)
    mongo_tracker = db_mongo.load_tracker_from_mongo()
    if mongo_tracker:
        save_tracker(mongo_tracker)
        return mongo_tracker

    # 2. Fallback: Local tracker file
    if not os.path.exists(TRACKER_FILE):
        return {"channel": "allterapost", "last_processed_id": 28824, "processed_ids": [28823, 28824]}
    try:
        with open(TRACKER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            if data.get("last_processed_id", 0) < 28824:
                data["last_processed_id"] = 28824
                if 28824 not in data.setdefault("processed_ids", []):
                    data["processed_ids"].append(28824)
            return data
    except:
        return {"channel": "allterapost", "last_processed_id": 28824, "processed_ids": [28823, 28824]}

def save_tracker(data):
    try:
        with open(TRACKER_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        print(f"[!] Warning saving local tracker: {e}")

async def sync_tracker_from_cloud(client):
    """Fetches persistent tracker JSON from Telegram Saved Messages ('me')."""
    try:
        async for msg in client.iter_messages('me', search="GM_TRACKER:", limit=5):
            if msg.text and msg.text.startswith("GM_TRACKER:"):
                raw_json = msg.text[len("GM_TRACKER:"):].strip()
                data = json.loads(raw_json)
                print(f"[☁️] Synced Tracker from Telegram Cloud: Last ID #{data.get('last_processed_id')}")
                return data
    except Exception as e:
        print(f"[!] Cloud tracker sync notice: {e}")
    return None

async def save_tracker_to_cloud(client_or_config, tracker_data):
    """Persists tracker JSON to Telegram Saved Messages ('me') to survive Render container rebuilds."""
    close_client = False
    if isinstance(client_or_config, TelegramClient):
        client = client_or_config
    else:
        tg_cfg = client_or_config.get("telegram", {})
        api_id = tg_cfg.get("api_id")
        api_hash = tg_cfg.get("api_hash")
        string_sess = tg_cfg.get("string_session")
        if string_sess:
            client = TelegramClient(StringSession(string_sess), api_id, api_hash)
        else:
            session_file = os.path.join(os.path.dirname(__file__), "telethon_session")
            client = TelegramClient(session_file, api_id, api_hash)
        await client.connect()
        close_client = True

    try:
        payload = f"GM_TRACKER:{json.dumps(tracker_data)}"
        target_msg = None
        async for msg in client.iter_messages('me', search="GM_TRACKER:", limit=5):
            if msg.text and msg.text.startswith("GM_TRACKER:"):
                target_msg = msg
                break

        if target_msg:
            await target_msg.edit(payload)
            print(f"[☁️] Persistent Cloud Tracker updated in Saved Messages (ID #{tracker_data.get('last_processed_id')})")
        else:
            await client.send_message('me', payload)
            print(f"[☁️] Persistent Cloud Tracker created in Saved Messages (ID #{tracker_data.get('last_processed_id')})")
    except Exception as e:
        print(f"[!] Warning writing cloud tracker: {e}")
    finally:
        if close_client:
            await client.disconnect()

def get_instagram_posted_ids(config):
    """Cross-checks live Instagram profile to ensure no already-posted reels are duplicated."""
    meta_cfg = config.get("meta", {})
    ig_user_id = meta_cfg.get("instagram_id")
    page_token = meta_cfg.get("page_token")
    if not ig_user_id or not page_token:
        return set()

    url = f"https://graph.facebook.com/v22.0/{ig_user_id}/media"
    params = {"fields": "id,caption", "access_token": page_token, "limit": 30}
    posted = set()
    try:
        r = requests.get(url, params=params, timeout=12)
        if r.status_code == 200:
            for item in r.json().get("data", []):
                cap = item.get("caption", "")
                for m_id in re.findall(r"#tg(\d+)", cap):
                    posted.add(int(m_id))
    except Exception as e:
        print(f"[!] IG cross-check notice: {e}")
    return posted

def _run_coroutine(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result()
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)

async def get_next_video(config, download_dir):
    """
    Connects to Telegram, synchronizes cloud tracker state,
    finds the oldest unposted video, downloads it,
    and returns (file_path, message_id, raw_caption).
    """
    tg_cfg = config.get("telegram", {})
    api_id = tg_cfg.get("api_id")
    api_hash = tg_cfg.get("api_hash")
    channel_name = tg_cfg.get("channel_username", "allterapost")
    string_sess = tg_cfg.get("string_session")

    if string_sess:
        client = TelegramClient(StringSession(string_sess), api_id, api_hash)
    else:
        session_file = os.path.join(os.path.dirname(__file__), "telethon_session")
        client = TelegramClient(session_file, api_id, api_hash)

    await client.connect()

    if not await client.is_user_authorized():
        print("\n" + "="*60)
        print("FIRST TIME TELEGRAM LOGIN REQUIRED")
        print("Telegram will send a login code to your Telegram app.")
        print("="*60)
        await client.start()
        print("[+] Telegram Authentication Successful!")

    print(f"[*] Accessing channel: {channel_name}...")
    channel = await client.get_entity(channel_name)

    # 1. Sync state with MongoDB Atlas and Telegram Cloud ('me' Saved Messages)
    tracker = load_tracker()
    cloud_tracker = await sync_tracker_from_cloud(client)
    if cloud_tracker:
        cloud_last_id = cloud_tracker.get("last_processed_id", 0)
        local_last_id = tracker.get("last_processed_id", 0)
        tracker["last_processed_id"] = max(cloud_last_id, local_last_id)
        merged_set = set(tracker.get("processed_ids", [])) | set(cloud_tracker.get("processed_ids", []))
        tracker["processed_ids"] = sorted(list(merged_set))
        save_tracker(tracker)
        db_mongo.save_tracker_to_mongo(tracker)
    elif tracker:
        db_mongo.save_tracker_to_mongo(tracker)

    # 2. Cross-check live Instagram posts
    ig_posted_ids = get_instagram_posted_ids(config)

    last_id = tracker.get("last_processed_id", 28824)
    processed_set = set(tracker.get("processed_ids", [])) | ig_posted_ids | {28823, 28824}
    print(f"[*] Last processed message ID: {last_id}. Searching for oldest next video (Skipping {len(processed_set)} known IDs)...")

    os.makedirs(download_dir, exist_ok=True)
    target_msg = None

    # Fetch messages in reverse (oldest first, starting after last_id)
    async for msg in client.iter_messages(channel, min_id=last_id, reverse=True, limit=100):
        if msg.id in processed_set:
            continue
        
        # Check if message contains video
        is_video = False
        if msg.video:
            is_video = True
        elif msg.media and hasattr(msg.media, "document"):
            mime = getattr(msg.media.document, "mime_type", "")
            if mime.startswith("video/"):
                is_video = True

        if is_video:
            target_msg = msg
            break

    if not target_msg:
        print("[*] No new unprocessed videos found in channel history.")
        await client.disconnect()
        return None

    print(f"[*] Found Video Message ID: {target_msg.id} (Date: {target_msg.date})")
    dest_path = os.path.join(download_dir, f"video_msg_{target_msg.id}.mp4")

    print(f"[*] Downloading video to {dest_path}...")
    def progress_callback(current, total):
        pct = (current / total) * 100
        sys.stdout.write(f"\r    Downloading: {pct:.1f}% ({current/(1024*1024):.1f}/{total/(1024*1024):.1f} MB)")
        sys.stdout.flush()

    file_path = await target_msg.download_media(file=dest_path, progress_callback=progress_callback)
    print(f"\n[+] Download complete: {file_path}")

    raw_caption = target_msg.text or ""
    await client.disconnect()

    return {
        "file_path": file_path,
        "message_id": target_msg.id,
        "raw_caption": raw_caption,
        "date": str(target_msg.date)
    }

def mark_video_processed(message_id, config=None):
    """Marks video as processed locally, in MongoDB Atlas, and persists state to Telegram Cloud."""
    tracker = load_tracker()
    tracker["last_processed_id"] = max(tracker.get("last_processed_id", 0), message_id)
    p_set = set(tracker.get("processed_ids", []))
    p_set.add(message_id)
    tracker["processed_ids"] = sorted(list(p_set))
    save_tracker(tracker)

    # 1. Persist to MongoDB Atlas
    db_mongo.save_tracker_to_mongo(tracker)

    # 2. Persist to Telegram Cloud ('me' Saved Messages)
    if config:
        try:
            _run_coroutine(save_tracker_to_cloud(config, tracker))
        except Exception as e:
            print(f"[!] Cloud sync notice: {e}")
