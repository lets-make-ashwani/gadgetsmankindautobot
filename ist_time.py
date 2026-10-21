from datetime import datetime, timezone, timedelta

# Indian Standard Time (IST) is UTC+05:30
IST = timezone(timedelta(hours=5, minutes=30))

def now_ist():
    """Returns current datetime object localized to Indian Standard Time (IST)."""
    return datetime.now(IST)

def now_ist_str(fmt="%Y-%m-%d %H:%M:%S IST"):
    """Returns formatted string of current time in IST."""
    return now_ist().strftime(fmt)

def now_ist_iso():
    """Returns ISO 8601 string with +05:30 offset."""
    return now_ist().isoformat()

def format_ts_to_ist(ts_str):
    """
    Ensures any timestamp (including past UTC logs or new IST logs)
    displays cleanly in Indian Standard Time (IST).
    """
    if not ts_str:
        return ""
    if "IST" in str(ts_str):
        return str(ts_str)
    try:
        clean_ts = str(ts_str).strip()[:19]
        dt = datetime.strptime(clean_ts, "%Y-%m-%d %H:%M:%S")
        # Convert earlier UTC server logs (+5h 30m) into IST
        dt_ist = dt + timedelta(hours=5, minutes=30)
        return dt_ist.strftime("%Y-%m-%d %H:%M:%S IST")
    except Exception:
        return f"{ts_str} IST"
