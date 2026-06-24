"""Application settings and shared HTTP client."""
import os
import shutil
import sys
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")

if os.getenv("MINIMAX_BASE_URL"):
    MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL").rstrip("/")
elif MINIMAX_API_KEY.startswith("sk-api"):
    MINIMAX_BASE_URL = "https://api.minimax.chat/v1"
else:
    MINIMAX_BASE_URL = "https://api.minimax.io/v1"

WORKSPACE_ROOT = os.path.join(os.path.dirname(__file__), "..", "workspace")
WORKSPACE_ROOT = os.path.abspath(WORKSPACE_ROOT)
os.makedirs(WORKSPACE_ROOT, exist_ok=True)

# Legacy alias used by docker-compose volume mapping
OUTPUT_DIR = WORKSPACE_ROOT

AUTH_HEADERS = {
    "Authorization": f"Bearer {MINIMAX_API_KEY}",
    "Content-Type": "application/json",
}

http = requests.Session()
http.headers.update(AUTH_HEADERS)
http.timeout = 120


def bootstrap():
    """Validate environment before serving requests."""
    import logging

    log = logging.getLogger("lincut")
    if not MINIMAX_API_KEY:
        log.error("MINIMAX_API_KEY not set. Copy .env.example to .env and add your key.")
        sys.exit(1)
    log.info("MiniMax endpoint: %s", MINIMAX_BASE_URL)

    missing = [cmd for cmd in ("ffmpeg", "ffprobe") if not shutil.which(cmd)]
    if missing:
        log.error(
            "%s not found in PATH. Install with: brew install ffmpeg",
            ", ".join(missing),
        )
        sys.exit(1)
