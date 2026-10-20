import os
import sys
import json
import time
import argparse
import asyncio
from datetime import datetime

# UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import telegram_extractor
import ai_dubber
import publisher
import config_loader
import db_mongo
import affiliate_manager

BASE_DIR = os.path.dirname(__file__)
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
PROCESSED_DIR = os.path.join(BASE_DIR, "processed")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

def load_config():
    return config_loader.load_config()

def cleanup_temporary_files(file_paths):
    """
    Zero-Footprint: Safely deletes temporary media files from disk immediately after use
    to stay well within Render's free tier ephemeral disk quota.
    """
    for path in file_paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
                print(f"[🧹] Zero-Footprint: Cleaned up temporary file: {path}")
            except Exception as e:
                print(f"[!] Warning cleaning temporary file {path}: {e}")

def sweep_disk_cache():
    """
    Zero-Footprint: Purges any leftover or orphaned media files from downloads/ and processed/
    directories to guarantee persistent zero-byte media footprint.
    """
    cleaned_count = 0
    for folder in [DOWNLOAD_DIR, PROCESSED_DIR]:
        if not os.path.exists(folder):
            continue
        for root, _, files in os.walk(folder):
            for f in files:
                ext = os.path.splitext(f)[1].lower()
                if ext in [".mp4", ".mp3", ".wav", ".m4a", ".tmp", ".part"]:
                    file_p = os.path.join(root, f)
                    try:
                        os.remove(file_p)
                        cleaned_count += 1
                    except Exception as e:
                        print(f"[!] Warning cleaning orphaned file {file_p}: {e}")
    if cleaned_count > 0:
        print(f"[🧹] Zero-Footprint: Swept {cleaned_count} leftover media file(s) from disk cache.")

def log_post_result(result_entry):
    os.makedirs(LOGS_DIR, exist_ok=True)
    history_file = os.path.join(LOGS_DIR, "post_history.json")
    history = []
    if os.path.exists(history_file):
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            history = []
    history.append(result_entry)
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=4, ensure_ascii=False)

    # Persist log to MongoDB Atlas
    db_mongo.log_post_to_mongo(result_entry)

def execute_pipeline_cycle():
    """
    Executes one complete cycle:
    1. Fetch oldest unposted video from Telegram
    2. Transcribe & translate Hindi to English via Groq Whisper
    3. Generate English voiceover via Edge-TTS & merge with FFmpeg
    4. Publish to Instagram Reels & Facebook Page
    5. Update tracker
    """
    config = load_config()
    print("\n" + "="*70)
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] STARTING GADGETS MANKIND AUTOMATION CYCLE")
    print("="*70)

    # 1. Fetch next video from Telegram
    video_item = asyncio.run(telegram_extractor.get_next_video(config, DOWNLOAD_DIR))
    if not video_item:
        print("[!] No new video available to process. Pipeline waiting.")
        return False

    raw_video_path = video_item["file_path"]
    message_id = video_item["message_id"]
    final_video_path = None

    try:
        # 2. AI Dubbing & Caption Generation
        try:
            dub_result = ai_dubber.process_video_ai(raw_video_path, PROCESSED_DIR, config)
        except Exception as e:
            print(f"[X] AI Dubbing failed for Message ID {message_id}: {e}")
            return False

        final_video_path = dub_result["final_video"]
        viral_caption = dub_result["caption"]
        summary = dub_result["summary"]
        product_name = dub_result.get("product_name", summary)

        # Register Amazon.in affiliate link for this product
        aff_record = affiliate_manager.register_product_affiliate(message_id, product_name)
        amazon_link = aff_record.get("amazon_affiliate_link", "")

        # Embed message ID tag into caption for persistent Instagram duplicate prevention
        if f"#tg{message_id}" not in viral_caption:
            viral_caption = f"{viral_caption}\n\n#tg{message_id}"

        print("\n" + "-"*60)
        print("AI CONTENT & AFFILIATE LINK GENERATED:")
        print(f"Product: {product_name}")
        print(f"Amazon Affiliate Link: {amazon_link}")
        print(f"Summary: {summary}")
        print(f"Caption preview:\n{viral_caption[:180]}...")
        print("-"*60 + "\n")

        # 3. Publish to Instagram Reels
        ig_success, ig_link_or_err = False, None
        if config["pipeline"].get("post_to_instagram", True):
            ig_success, ig_link_or_err = publisher.upload_instagram_reel(final_video_path, viral_caption, config)
            if ig_success:
                print(f"[+] INSTAGRAM REEL LIVE: {ig_link_or_err}")
                # Associate published media with product in affiliate catalog
                affiliate_manager.update_media_id_for_product(message_id, ig_link_or_err)
            else:
                print(f"[-] Instagram upload failed: {ig_link_or_err}")

        # 4. Publish to Facebook Page
        fb_success, fb_id_or_err = False, None
        if config["pipeline"].get("post_to_facebook", True):
            fb_success, fb_id_or_err = publisher.upload_facebook_video(final_video_path, viral_caption, config)
            if fb_success:
                print(f"[+] FACEBOOK VIDEO LIVE: ID {fb_id_or_err}")
            else:
                print(f"[-] Facebook upload failed: {fb_id_or_err}")

        # 5. Mark as processed & Log (persisting to Telegram Cloud & MongoDB)
        telegram_extractor.mark_video_processed(message_id, config)

        log_entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "telegram_message_id": message_id,
            "product_name": product_name,
            "amazon_link": amazon_link,
            "summary": summary,
            "instagram": {"success": ig_success, "result": ig_link_or_err},
            "facebook": {"success": fb_success, "result": fb_id_or_err},
            "caption": viral_caption,
            "video_file": final_video_path
        }
        log_post_result(log_entry)

        print("\n" + "="*70)
        print(f"[+] CYCLE FINISHED SUCCESSFULLY FOR TELEGRAM MESSAGE #{message_id}")
        print("="*70 + "\n")
        return True
    finally:
        # Zero-Footprint: Clean up downloaded raw video and final dubbed video immediately after upload
        cleanup_targets = [p for p in [raw_video_path, final_video_path] if p]
        cleanup_temporary_files(cleanup_targets)

def main():
    parser = argparse.ArgumentParser(description="Gadgets Mankind Automation Pipeline")
    parser.add_argument("--run-once", action="store_true", help="Process only 1 video immediately and exit")
    args = parser.parse_args()

    # Zero-Footprint: Clean up any stale media files from previous container crashes or restarts
    sweep_disk_cache()

    config = load_config()
    interval_hours = config.get("pipeline", {}).get("interval_hours", 3)
    interval_seconds = int(interval_hours * 3600)

    if args.run_once:
        print("[*] Running in Single Execution mode (--run-once)...")
        execute_pipeline_cycle()
        return

    print(f"[*] Starting Continuous Automation Loop (Interval: every {interval_hours} hours)...")
    while True:
        try:
            execute_pipeline_cycle()
        except Exception as e:
            print(f"[X] Unhandled exception in pipeline loop: {e}")

        print(f"[*] Sleeping for {interval_hours} hours until next cycle...")
        time.sleep(interval_seconds)

if __name__ == "__main__":
    main()
