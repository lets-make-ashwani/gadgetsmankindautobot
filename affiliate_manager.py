import os
import sys
import re
import urllib.parse
from datetime import datetime
import db_mongo
import ist_time

# UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DEFAULT_AMAZON_TAG = "tech6s-21"
DEFAULT_MARKETPLACE = "amazon.in"

_memory_catalog = {}

def get_amazon_tag():
    return os.environ.get("AMAZON_AFFILIATE_TAG", DEFAULT_AMAZON_TAG).strip()

def clean_search_term(text):
    if not text:
        return "trending gadgets"
    # remove punctuation, emojis, extra symbols, keep alphanumeric and spaces
    cleaned = re.sub(r'[^\w\s]', ' ', text)
    words = [w.strip() for w in cleaned.split() if len(w.strip()) > 1][:6]
    return " ".join(words) if words else "trending gadgets"

def generate_smart_app_link(product_title_or_query):
    """
    Generates a smart deep link that instructs mobile browsers (Instagram in-app browser)
    to bypass the web view and launch the native Amazon Shopping App directly.
    """
    tag = get_amazon_tag()
    clean_query = clean_search_term(product_title_or_query)
    encoded = urllib.parse.quote_plus(clean_query)
    return f"https://gadgetsmankindautobot.onrender.com/open?q={encoded}&tag={tag}"

def generate_amazon_affiliate_link(product_title_or_query):
    """
    Generates a high-converting, targeted Amazon.in search affiliate link
    for the exact product featured in the reel.
    """
    tag = get_amazon_tag()
    clean_query = clean_search_term(product_title_or_query)
    encoded_query = urllib.parse.quote_plus(clean_query)
    affiliate_url = f"https://www.amazon.in/s?k={encoded_query}&tag={tag}"
    return affiliate_url, clean_query

DEFAULT_PRODUCT_IMAGE = "https://images-eu.ssl-images-amazon.com/images/G/31/AmazonBusiness/AB_logo_1200x630.png"

def register_product_affiliate(telegram_message_id, product_name, instagram_media_id=None, image_url=None):
    """
    Registers the affiliate link for this product in MongoDB and memory
    so Auto-DM can instantly look it up when users comment on the reel.
    """
    tag = get_amazon_tag()
    affiliate_link, clean_query = generate_amazon_affiliate_link(product_name)

    record = {
        "telegram_message_id": int(telegram_message_id) if str(telegram_message_id).isdigit() else telegram_message_id,
        "instagram_media_id": str(instagram_media_id) if instagram_media_id else None,
        "product_name": product_name,
        "clean_search_query": clean_query,
        "amazon_affiliate_link": affiliate_link,
        "image_url": image_url or DEFAULT_PRODUCT_IMAGE,
        "tag": tag,
        "timestamp": ist_time.now_ist_str()
    }

    # Store in memory
    _memory_catalog[str(telegram_message_id)] = record
    if instagram_media_id:
        _memory_catalog[str(instagram_media_id)] = record

    # Store in MongoDB Atlas if available
    db = db_mongo.get_db()
    if db is not None:
        try:
            db["affiliate_catalog"].update_one(
                {"telegram_message_id": record["telegram_message_id"]},
                {"$set": record},
                upsert=True
            )
            print(f"[🏷️] Amazon Affiliate Link Registered: {clean_query} ➔ tag={tag}")
        except Exception as e:
            print(f"[!] Warning persisting affiliate record to MongoDB: {e}")

    return record

def update_media_id_for_product(telegram_message_id, instagram_media_id):
    """Associates the live Instagram Reel media ID with the product once published."""
    if not instagram_media_id:
        return

    m_id_str = str(instagram_media_id)
    t_id_str = str(telegram_message_id)

    if t_id_str in _memory_catalog:
        _memory_catalog[t_id_str]["instagram_media_id"] = m_id_str
        _memory_catalog[m_id_str] = _memory_catalog[t_id_str]

    db = db_mongo.get_db()
    if db is not None:
        try:
            db["affiliate_catalog"].update_one(
                {"telegram_message_id": int(telegram_message_id) if str(telegram_message_id).isdigit() else telegram_message_id},
                {"$set": {"instagram_media_id": m_id_str}}
            )
        except Exception as e:
            print(f"[!] Error updating media_id in affiliate catalog: {e}")

def get_product_for_media(instagram_media_id=None, telegram_message_id=None):
    """
    Finds product record and Amazon affiliate link by Instagram media ID or Telegram message ID.
    Falls back to the most recently registered product if specific ID is not found.
    """
    # 1. Check memory cache
    if instagram_media_id and str(instagram_media_id) in _memory_catalog:
        return _memory_catalog[str(instagram_media_id)]
    if telegram_message_id and str(telegram_message_id) in _memory_catalog:
        return _memory_catalog[str(telegram_message_id)]

    # 2. Check MongoDB Atlas
    db = db_mongo.get_db()
    if db is not None:
        try:
            if instagram_media_id:
                doc = db["affiliate_catalog"].find_one({"instagram_media_id": str(instagram_media_id)})
                if doc:
                    return doc
            if telegram_message_id:
                doc = db["affiliate_catalog"].find_one({"telegram_message_id": int(telegram_message_id) if str(telegram_message_id).isdigit() else telegram_message_id})
                if doc:
                    return doc

            # Fallback to latest registered product
            latest = db["affiliate_catalog"].find_one(sort=[("timestamp", -1)])
            if latest:
                return latest
        except Exception as e:
            print(f"[!] Warning querying affiliate catalog: {e}")

    # 3. Ultimate Fallback: General gadget search link with user's affiliate tag
    tag = get_amazon_tag()
    return {
        "product_name": "Trending Amazon Gadget",
        "amazon_affiliate_link": f"https://www.amazon.in/s?k=trending+home+kitchen+gadgets&tag={tag}",
        "image_url": DEFAULT_PRODUCT_IMAGE,
        "tag": tag
    }
