import sys
import threading
from datetime import datetime
from collections import deque

class LogStreamer:
    def __init__(self, max_lines=150):
        self.max_lines = max_lines
        self.buffer = deque(maxlen=max_lines)
        self.lock = threading.Lock()
        self._stdout = sys.stdout
        self._stderr = sys.stderr

    def write(self, message):
        self._stdout.write(message)
        if message and message.strip():
            with self.lock:
                timestamp = datetime.now().strftime("%H:%M:%S")
                for line in message.strip().split("\n"):
                    clean = line.strip()
                    if clean:
                        self.buffer.append(f"[{timestamp}] {clean}")

    def flush(self):
        self._stdout.flush()

    def get_logs(self, limit=100):
        with self.lock:
            return list(self.buffer)[-limit:]

_streamer = None

def init_log_streamer():
    global _streamer
    if _streamer is None:
        _streamer = LogStreamer()
        sys.stdout = _streamer
    return _streamer

def get_logs(limit=100):
    global _streamer
    if _streamer is None:
        return []
    return _streamer.get_logs(limit)
