import os
import sys
import json
import asyncio
from telethon import TelegramClient
from telethon.sessions import StringSession

# UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

TRACKER_FILE = os.path.join(os.path.dirname(__file__), "tracker.json")

def load_tracker():
    if not os.path.exists(TRACKER_FILE):
        return {"channel": "allterapost", "last_processed_id": 0, "processed_ids": []}
    try:
        with open(TRACKER_FILE, "r") as f:
            return json.load(f)
    except:
        return {"channel": "allterapost", "last_processed_id": 0, "processed_ids": []}

def save_tracker(data):
    with open(TRACKER_FILE, "w") as f:
        json.dump(data, f, indent=4)

async def get_next_video(config, download_dir):
    """
    Connects to Telegram, finds the oldest unposted video, downloads it,
    and returns (file_path, message_id, raw_caption).
    Supports both StringSession (for Render/Cloud) and local file session.
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

    tracker = load_tracker()
    last_id = tracker.get("last_processed_id", 0)
    processed_set = set(tracker.get("processed_ids", []))
    print(f"[*] Last processed message ID: {last_id}. Searching for oldest next video...")

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

def mark_video_processed(message_id):
    tracker = load_tracker()
    tracker["last_processed_id"] = message_id
    if message_id not in tracker.get("processed_ids", []):
        tracker.setdefault("processed_ids", []).append(message_id)
    save_tracker(tracker)
