import os
import sys
import json
import time
import re
import urllib.parse
import requests
from datetime import datetime
import db_mongo
import affiliate_manager
import ist_time

# UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_VERIFY_TOKEN = os.environ.get("META_VERIFY_TOKEN", "gadgets_mankind_autodm_secret_token_2026")

_replied_comments = set()

def extract_product_title(caption):
    """
    Intelligently parses the exact product title from the Reel caption.
    """
    if not caption:
        return "Trending Amazon Gadget"
    
    # 1. Check if caption has an Amazon buy link with search query ?k=...
    link_match = re.search(r'amazon\.in/s\?k=([^&\s]+)', caption)
    if link_match:
        raw_k = link_match.group(1)
        decoded = urllib.parse.unquote_plus(raw_k).strip()
        if decoded:
            return decoded.title()
            
    # 2. Parse lines
    for line in caption.split("\n"):
        l = line.strip()
        if not l:
            continue
        # Skip emojis or meta lines
        if any(l.startswith(prefix) for prefix in ["💬", "🚫", "#", "🛒", "👉", "✨", "Hey", "Comment"]):
            continue
        # Candidate line (e.g. "Reusable Shower Drain Pipe Cover Stickers — Easy to stick...")
        candidate = re.split(r'[—:\-]', l)[0].strip()
        if len(candidate) >= 3 and len(candidate) <= 70:
            return candidate
            
    return "Trending Amazon Gadget"

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
                    "replied_at": ist_time.now_ist_str()
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

def send_private_dm_reply(comment_id, username, media_id, config, caption=None):
    """
    Sends official Meta Instagram Private Reply to a comment on a Reel,
    delivering the Amazon India affiliate link directly into the user's DMs.
    Uses Smart App Opener so tapping opens directly inside the Amazon App!
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

    # 2. If not found or generic fallback, dynamically resolve product via Reel Caption
    if (not product_info or product_info.get("product_name") == "Trending Amazon Gadget"):
        # If caption wasn't passed, fetch it directly via Meta Graph API
        if not caption and media_id:
            try:
                m_res = requests.get(
                    f"https://graph.facebook.com/v22.0/{media_id}",
                    params={"fields": "caption", "access_token": page_token},
                    timeout=6
                ).json()
                caption = m_res.get("caption")
            except Exception:
                pass

        if caption:
            # Check for #tg12345
            m_tg = re.search(r'#tg(\d+)', caption)
            if m_tg:
                tg_id = int(m_tg.group(1))
                found_prod = affiliate_manager.get_product_for_media(telegram_message_id=tg_id)
                if found_prod and found_prod.get("product_name") != "Trending Amazon Gadget":
                    product_info = found_prod

            # If still default, parse product name directly from caption
            if not product_info or product_info.get("product_name") == "Trending Amazon Gadget":
                extracted_name = extract_product_title(caption)
                if extracted_name and extracted_name != "Trending Amazon Gadget":
                    aff_url, clean_q = affiliate_manager.generate_amazon_affiliate_link(extracted_name)
                    product_info = {
                        "product_name": extracted_name,
                        "clean_search_query": clean_q,
                        "amazon_affiliate_link": aff_url,
                        "image_url": affiliate_manager.DEFAULT_PRODUCT_IMAGE,
                        "tag": affiliate_manager.get_amazon_tag()
                    }

    product_name = product_info.get("product_name", "Featured Gadget") if product_info else "Featured Gadget"
    # Smart app opener link for launching native Amazon App directly
    smart_app_link = affiliate_manager.generate_smart_app_link(product_name)
    image_url = (product_info.get("image_url") or affiliate_manager.DEFAULT_PRODUCT_IMAGE) if product_info else affiliate_manager.DEFAULT_PRODUCT_IMAGE

    api_url = f"https://graph.facebook.com/v22.0/{page_id}/messages"

    # 3. Primary: Interactive Product Card with "Shop on Amazon" Button (Image 2 Style)
    card_payload = {
        "recipient": {"comment_id": str(comment_id)},
        "message": {
            "attachment": {
                "type": "template",
                "payload": {
                    "template_type": "generic",
                    "elements": [
                        {
                            "title": product_name[:80],
                            "subtitle": "Amazon.in • Tap below to open in Amazon App",
                            "image_url": image_url,
                            "default_action": {
                                "type": "web_url",
                                "url": smart_app_link
                            },
                            "buttons": [
                                {
                                    "type": "web_url",
                                    "url": smart_app_link,
                                    "title": "Shop on Amazon 🛍️"
                                }
                            ]
                        }
                    ]
                }
            }
        },
        "access_token": page_token
    }

    try:
        r = requests.post(api_url, json=card_payload, timeout=15)
        res = r.json()
        if "message_id" in res or "recipient_id" in res or res.get("success"):
            print(f"[🛍️] Interactive Product Card Sent to @{username} for {product_name} (Comment #{comment_id})")
            mark_comment_replied(comment_id, username, media_id, product_name, smart_app_link)
            return True, "Product Card Sent Successfully"
        else:
            print(f"[!] Card delivery response: {res}. Falling back to clean text DM...")
    except Exception as e:
        print(f"[!] Card delivery glitch: {e}. Falling back to clean text DM...")

    # 4. Fallback: Clean formatted text DM with Smart App Link
    greeting = f"Hey @{username}! 🙌" if username and username != "friend" else "Hey there! 🙌"
    dm_text = (
        f"{greeting} Thanks for commenting on our reel!\n\n"
        f"Here is your direct Amazon link for the *{product_name}*:\n"
        f"👉 {smart_app_link}\n\n"
        f"(Tapping opens directly in your Amazon app! 🛒✨)\n\n"
        f"Enjoy shopping! Let me know if you need any other cool gadget recommendations! ✨🛍️"
    )

    payload = {
        "recipient": {"comment_id": str(comment_id)},
        "message": {"text": dm_text},
        "access_token": page_token
    }

    try:
        r = requests.post(api_url, json=payload, timeout=15)
        res = r.json()
        if "message_id" in res or "recipient_id" in res or res.get("success"):
            print(f"[📩] Fallback Auto-DM Sent to @{username} for {product_name} (Comment #{comment_id})")
            mark_comment_replied(comment_id, username, media_id, product_name, smart_app_link)
            return True, "DM Sent Successfully"
        else:
            print(f"[!] Auto-DM delivery response: {res}")
            if "error" in res and res["error"].get("code") in [100, 230]:
                mark_comment_replied(comment_id, username, media_id, product_name, smart_app_link)
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
            caption = item.get("caption", "")
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
                    success, msg = send_private_dm_reply(c_id, username, m_id, config, caption=caption)
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
