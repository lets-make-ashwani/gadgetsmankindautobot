import os
import sys
import json
import time
import requests
from datetime import datetime
import db_mongo
import affiliate_manager

# UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "gadgets_mankind_autodm_secret_token_2026")

_replied_comments = set()

def is_comment_replied(comment_id):
    if str(comment_id) in _replied_comments:
        return True
    db = db_mongo.get_db()
    if db is not None:
        try:
            return db["autodm_replies"].find_one({"comment_id": str(comment_id)}) is not None
        except:
            pass
    return False

def mark_comment_replied(comment_id, username, media_id, product_name, affiliate_link):
    _replied_comments.add(str(comment_id))
    db = db_mongo.get_db()
    if db is not None:
        try:
            db["autodm_replies"].update_one(
                {"comment_id": str(comment_id)},
                {"$set": {
                    "comment_id": str(comment_id),
                    "username": username,
                    "media_id": str(media_id) if media_id else None,
                    "product_name": product_name,
                    "affiliate_link": affiliate_link,
                    "replied_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }},
                upsert=True
            )
        except Exception as e:
            print(f"[!] Warning caching replied comment in MongoDB: {e}")

def get_autodm_stats():
    """Returns total count of Auto-DMs successfully delivered."""
    count = len(_replied_comments)
    db = db_mongo.get_db()
    if db is not None:
        try:
            count = max(count, db["autodm_replies"].count_documents({}))
        except:
            pass
    return count

def send_private_dm_reply(comment_id, username, media_id, config):
    """
    Sends official Meta Instagram Private Reply to a comment on a Reel,
    delivering the Amazon India affiliate link directly into the user's DMs.
    """
    if is_comment_replied(comment_id):
        return False, "Already replied"

    meta_cfg = config.get("meta", {})
    page_id = meta_cfg.get("page_id")
    page_token = meta_cfg.get("page_token")
    if not page_id or not page_token:
        return False, "Missing Meta Page credentials"

    # 1. Lookup exact product & affiliate link for this Reel
    product_info = affiliate_manager.get_product_for_media(instagram_media_id=media_id)
    product_name = product_info.get("product_name", "Featured Gadget")
    affiliate_link = product_info.get("amazon_affiliate_link", "https://www.amazon.in")

    # 2. Craft high-converting DM copy
    greeting = f"Hey @{username}! 👋" if username and username != "friend" else "Hey there! 👋"
    dm_text = (
        f"{greeting}\n\n"
        f"Here is the direct Amazon India link for the {product_name} you asked about:\n\n"
        f"🔗 {affiliate_link}\n\n"
        f"⚡ Fast shipping & best deals available on Amazon.in!\n"
        f"Feel free to reply if you need any other gadget recommendations! ✨\n\n"
        f"(As an Amazon Associate, I earn from qualifying purchases)"
    )

    # 3. Call Meta Graph API for Private Reply to Comment
    api_url = f"https://graph.facebook.com/v22.0/{page_id}/messages"
    payload = {
        "recipient": {"comment_id": str(comment_id)},
        "message": {"text": dm_text},
        "access_token": page_token
    }

    try:
        r = requests.post(api_url, json=payload, timeout=15)
        res = r.json()
        if "message_id" in res or "recipient_id" in res or res.get("success"):
            print(f"[📩] Auto-DM Sent to @{username} for {product_name} (Comment #{comment_id})")
            mark_comment_replied(comment_id, username, media_id, product_name, affiliate_link)
            return True, "DM Sent Successfully"
        else:
            print(f"[!] Auto-DM delivery response: {res}")
            # Mark replied even if user privacy prevents DM to prevent retrying forever
            if "error" in res and res["error"].get("code") in [100, 230]:
                mark_comment_replied(comment_id, username, media_id, product_name, affiliate_link)
            return False, str(res)
    except Exception as e:
        print(f"[X] Auto-DM network error: {e}")
        return False, str(e)

def scan_and_reply_recent_comments(config):
    """
    Background comment poller that checks the last 5 published Reels
    for new comments/emojis and sends Auto-DMs. Works automatically without
    requiring manual Webhook endpoint setup in Meta Developer portal.
    """
    meta_cfg = config.get("meta", {})
    ig_user_id = meta_cfg.get("instagram_id")
    page_token = meta_cfg.get("page_token")
    if not ig_user_id or not page_token:
        return 0

    replied_count = 0
    try:
        # Step 1: Get recent media reels
        media_url = f"https://graph.facebook.com/v22.0/{ig_user_id}/media"
        r_media = requests.get(media_url, params={"fields": "id,caption", "access_token": page_token, "limit": 5}, timeout=12)
        if r_media.status_code != 200:
            return 0

        media_items = r_media.json().get("data", [])
        for item in media_items:
            m_id = item.get("id")
            if not m_id:
                continue

            # Step 2: Get comments on this media
            comments_url = f"https://graph.facebook.com/v22.0/{m_id}/comments"
            r_comments = requests.get(comments_url, params={"fields": "id,text,from,timestamp", "access_token": page_token, "limit": 15}, timeout=12)
            if r_comments.status_code != 200:
                continue

            comments = r_comments.json().get("data", [])
            for c in comments:
                c_id = c.get("id")
                c_from = c.get("from", {})
                username = c_from.get("username", "friend")
                
                # Skip comments from our own bot account
                if username == meta_cfg.get("instagram_username", "gadgetsmankind"):
                    continue

                if not is_comment_replied(c_id):
                    success, msg = send_private_dm_reply(c_id, username, m_id, config)
                    if success:
                        replied_count += 1
                    time.sleep(1) # respectful rate pacing

    except Exception as e:
        print(f"[!] Auto-DM background scanner note: {e}")

    return replied_count

def handle_webhook_event(data, config):
    """Handles incoming live Meta Webhooks when configured."""
    entry_list = data.get("entry", [])
    handled = 0
    for entry in entry_list:
        changes = entry.get("changes", [])
        for change in changes:
            field = change.get("field")
            value = change.get("value", {})
            if field == "comments":
                c_id = value.get("id")
                from_user = value.get("from", {})
                username = from_user.get("username", "friend")
                media = value.get("media", {})
                m_id = media.get("id")

                if c_id and not is_comment_replied(c_id):
                    success, _ = send_private_dm_reply(c_id, username, m_id, config)
                    if success:
                        handled += 1
    return handled
