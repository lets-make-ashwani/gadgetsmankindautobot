import os
import sys
from datetime import datetime

# UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

_client = None
_db = None
_mongo_uri_checked = None

def get_mongo_uri():
    return os.environ.get("MONGODB_URI", os.environ.get("MONGO_URI", "")).strip()

def get_db():
    global _client, _db, _mongo_uri_checked
    uri = get_mongo_uri()
    if not uri:
        return None

    if _client is not None and _mongo_uri_checked == uri:
        return _db

    try:
        from pymongo import MongoClient
        _client = MongoClient(uri, serverSelectionTimeoutMS=4000)
        # Verify connection with quick ping
        _client.admin.command('ping')
        db_name = os.environ.get("MONGODB_DATABASE", "gadgets_mankind")
        _db = _client[db_name]
        _mongo_uri_checked = uri
        print(f"[🍃] MongoDB Atlas Connected! (Database: {db_name})")
        return _db
    except Exception as e:
        print(f"[!] MongoDB Atlas connection failed: {e}")
        _client = None
        _db = None
        return None

def is_connected():
    db = get_db()
    return db is not None

def load_tracker_from_mongo():
    """
    Retrieves global tracker state from MongoDB Atlas.
    Returns dict if document exists, else None.
    """
    db = get_db()
    if db is None:
        return None

    try:
        doc = db["automation_state"].find_one({"_id": "global_tracker"})
        if doc:
            return {
                "channel": doc.get("channel", "allterapost"),
                "last_processed_id": doc.get("last_processed_id", 28824),
                "processed_ids": doc.get("processed_ids", [28823, 28824])
            }
    except Exception as e:
        print(f"[!] Warning reading tracker from MongoDB: {e}")
    return None

def save_tracker_to_mongo(tracker_data):
    """
    Persists global tracker state into MongoDB Atlas with upsert.
    """
    db = get_db()
    if db is None:
        return False

    try:
        payload = {
            "channel": tracker_data.get("channel", "allterapost"),
            "last_processed_id": tracker_data.get("last_processed_id", 28824),
            "processed_ids": tracker_data.get("processed_ids", [28823, 28824]),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        db["automation_state"].update_one(
            {"_id": "global_tracker"},
            {"$set": payload},
            upsert=True
        )
        print(f"[🍃] MongoDB Atlas: Tracker synchronized (Last ID #{payload['last_processed_id']})")
        return True
    except Exception as e:
        print(f"[!] Warning writing tracker to MongoDB: {e}")
        return False

def log_post_to_mongo(post_entry):
    """
    Saves published post log to MongoDB Atlas.
    """
    db = get_db()
    if db is None:
        return False

    try:
        entry_copy = dict(post_entry)
        entry_copy["created_at"] = datetime.utcnow()
        db["post_history"].insert_one(entry_copy)
        print(f"[🍃] MongoDB Atlas: Post logged for Telegram Msg #{post_entry.get('telegram_message_id')}")
        return True
    except Exception as e:
        print(f"[!] Warning logging post to MongoDB: {e}")
        return False

def load_recent_history_from_mongo(limit=10):
    """
    Loads recent published post logs from MongoDB Atlas.
    """
    db = get_db()
    if db is None:
        return None

    try:
        cursor = db["post_history"].find({}, {"_id": 0}).sort("timestamp", -1).limit(limit)
        return list(cursor)
    except Exception as e:
        print(f"[!] Warning loading history from MongoDB: {e}")
        return None
