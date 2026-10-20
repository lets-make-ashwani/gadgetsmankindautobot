import os
import json

# Try loading .env if dotenv is installed
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
except ImportError:
    pass

def load_config():
    """
    Unified configuration loader that priority reads from environment variables (Render.com),
    falling back to .env or local config.json.
    """
    # Base fallback from config.json if present
    cfg_file = os.path.join(os.path.dirname(__file__), "config.json")
    base_cfg = {}
    if os.path.exists(cfg_file):
        try:
            with open(cfg_file, "r", encoding="utf-8") as f:
                base_cfg = json.load(f)
        except:
            pass

    tg = base_cfg.get("telegram", {})
    gr = base_cfg.get("groq", {})
    mt = base_cfg.get("meta", {})
    pl = base_cfg.get("pipeline", {})

    # Overlay environment variables
    config = {
        "telegram": {
            "api_id": int(os.environ.get("TELEGRAM_API_ID", tg.get("api_id", 0))),
            "api_hash": os.environ.get("TELEGRAM_API_HASH", tg.get("api_hash", "")),
            "channel_username": os.environ.get("TELEGRAM_CHANNEL", tg.get("channel_username", "allterapost")),
            "string_session": os.environ.get("TELEGRAM_STRING_SESSION", tg.get("string_session", ""))
        },
        "groq": {
            "api_key": os.environ.get("GROQ_API_KEY", gr.get("api_key", "")),
            "transcription_model": os.environ.get("GROQ_TRANSCRIPTION_MODEL", gr.get("transcription_model", "whisper-large-v3")),
            "llm_model": os.environ.get("GROQ_LLM_MODEL", gr.get("llm_model", "openai/gpt-oss-120b")),
            "tts_voice": os.environ.get("GROQ_TTS_VOICE", gr.get("tts_voice", "en-US-ChristopherNeural"))
        },
        "meta": {
            "page_id": os.environ.get("META_PAGE_ID", mt.get("page_id", "")),
            "page_name": os.environ.get("META_PAGE_NAME", mt.get("page_name", "Gadgets mankind")),
            "page_token": os.environ.get("META_PAGE_TOKEN", mt.get("page_token", "")),
            "instagram_id": os.environ.get("META_INSTAGRAM_ID", mt.get("instagram_id", "")),
            "instagram_username": os.environ.get("META_INSTAGRAM_USERNAME", mt.get("instagram_username", "gadgetsmankind"))
        },
        "pipeline": {
            "order": os.environ.get("PIPELINE_ORDER", pl.get("order", "oldest_to_newest")),
            "interval_hours": float(os.environ.get("PIPELINE_INTERVAL_HOURS", pl.get("interval_hours", 3))),
            "auto_dub_english": os.environ.get("AUTO_DUB_ENGLISH", str(pl.get("auto_dub_english", True))).lower() in ["true", "1", "yes"],
            "post_to_instagram": os.environ.get("POST_TO_INSTAGRAM", str(pl.get("post_to_instagram", True))).lower() in ["true", "1", "yes"],
            "post_to_facebook": os.environ.get("POST_TO_FACEBOOK", str(pl.get("post_to_facebook", True))).lower() in ["true", "1", "yes"]
        }
    }

    return config
