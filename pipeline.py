import os
import sys
import json
import time
import argparse
import asyncio
from datetime import datetime
import ist_time

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
    print(f"[{ist_time.now_ist_str()}] STARTING GADGETS MANKIND AUTOMATION CYCLE")
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
        ig_caption = dub_result.get("ig_caption", dub_result.get("caption", ""))
        fb_desc = dub_result.get("fb_description", ig_caption)
        summary = dub_result["summary"]
        product_name = dub_result.get("product_name", summary)

        # Extract product thumbnail image for interactive DM card (Image 2 style)
        thumbnails_dir = os.path.join(BASE_DIR, "static", "thumbnails")
        os.makedirs(thumbnails_dir, exist_ok=True)
        thumb_filename = f"thumb_{message_id}.jpg"
        thumb_path = os.path.join(thumbnails_dir, thumb_filename)
        image_url = None
        try:
            import subprocess
            cmd_thumb = [
                "ffmpeg", "-y",
                "-ss", "00:00:02",
                "-i", raw_video_path,
                "-vframes", "1",
                "-q:v", "2",
                thumb_path
            ]
            subprocess.run(cmd_thumb, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if os.path.exists(thumb_path) and os.path.getsize(thumb_path) > 0:
                image_url = f"https://gadgetsmankindautobot.onrender.com/static/thumbnails/{thumb_filename}"
        except Exception as e:
            pass

        # Register Amazon.in affiliate link for this product
        aff_record = affiliate_manager.register_product_affiliate(message_id, product_name, image_url=image_url)
        amazon_link = aff_record.get("amazon_affiliate_link", "")

        # Format Instagram Reel Caption:
        # CTA strictly on Line 1, plus #tg{message_id} at bottom for tracking
        if f"#tg{message_id}" not in ig_caption:
            ig_caption = f"{ig_caption}\n\n#tg{message_id}"

        # Format Facebook Page Caption:
        # Line 1 MUST be the direct 1-click Amazon Buy Link!
        fb_caption = f"🛒 BUY LINK ➔ {amazon_link}\n\n{fb_desc}"

        print("\n" + "-"*60)
        print("AI CONTENT & AFFILIATE LINK GENERATED:")
        print(f"Product: {product_name}")
        print(f"Amazon Affiliate Link: {amazon_link}")
        print(f"Summary: {summary}")
        print(f"Instagram Caption Preview (CTA on Line 1):\n{ig_caption[:180]}...")
        print(f"Facebook Caption Preview (Buy Link on Line 1):\n{fb_caption[:180]}...")
        print("-"*60 + "\n")

        # 3. Publish to Instagram Reels
        ig_success, ig_link_or_err = False, None
        if config["pipeline"].get("post_to_instagram", True):
            ig_success, ig_link_or_err = publisher.upload_instagram_reel(final_video_path, ig_caption, config)
            if ig_success:
                print(f"[+] INSTAGRAM REEL LIVE: {ig_link_or_err}")
                # Associate published media with product in affiliate catalog
                affiliate_manager.update_media_id_for_product(message_id, ig_link_or_err)
            else:
                print(f"[-] Instagram upload failed: {ig_link_or_err}")

        # 4. Publish to Facebook Page
        fb_success, fb_id_or_err = False, None
        if config["pipeline"].get("post_to_facebook", True):
            fb_success, fb_id_or_err = publisher.upload_facebook_video(final_video_path, fb_caption, config)
            if fb_success:
                print(f"[+] FACEBOOK VIDEO LIVE: ID {fb_id_or_err}")
            else:
                print(f"[-] Facebook upload failed: {fb_id_or_err}")

        # 5. Strict Publish Confirmation Check
        req_ig = config["pipeline"].get("post_to_instagram", True)
        req_fb = config["pipeline"].get("post_to_facebook", True)

        upload_confirmed = True
        if req_ig and not ig_success:
            upload_confirmed = False
        if req_fb and not fb_success:
            upload_confirmed = False

        if not upload_confirmed:
            print("\n" + "!"*70)
            print(f"[!] PUBLISH CONFIRMATION FAILED FOR TELEGRAM MESSAGE #{message_id}")
            if req_ig and not ig_success:
                print(f"    [-] Instagram upload failed: {ig_link_or_err}")
            if req_fb and not fb_success:
                print(f"    [-] Facebook upload failed: {fb_id_or_err}")
            print(f"[!] PIPELINE BREAK: Message #{message_id} was NOT confirmed as published.")
            print(f"[!] Tracker NOT advanced. Video #{message_id} will be re-processed in the next cycle!")
            print("!"*70 + "\n")

            log_entry = {
                "timestamp": ist_time.now_ist_str(),
                "telegram_message_id": message_id,
                "product_name": product_name,
                "amazon_link": amazon_link,
                "summary": summary,
                "instagram": {"success": ig_success, "result": ig_link_or_err},
                "facebook": {"success": fb_success, "result": fb_id_or_err},
                "caption": ig_caption,
                "video_file": final_video_path,
                "status": "FAILED_CONFIRMATION_WILL_RETRY"
            }
            log_post_result(log_entry)
            return False

        # 6. Mark as processed & Log (ONLY when confirmed published!)
        telegram_extractor.mark_video_processed(message_id, config)

        log_entry = {
            "timestamp": ist_time.now_ist_str(),
            "telegram_message_id": message_id,
            "product_name": product_name,
            "amazon_link": amazon_link,
            "summary": summary,
            "instagram": {"success": ig_success, "result": ig_link_or_err},
            "facebook": {"success": fb_success, "result": fb_id_or_err},
            "caption": ig_caption,
            "video_file": final_video_path,
            "status": "CONFIRMED_PUBLISHED"
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
