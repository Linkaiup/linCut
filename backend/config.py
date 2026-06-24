"""Configuration and shared constants."""
import os
import shutil
import sys
import requests
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")

# MiniMax has two API regions; keys are not interchangeable:
#   International (platform.minimax.io):  https://api.minimax.io/v1   — keys often start with "eyJ"
#   China (platform.minimaxi.com):        https://api.minimax.chat/v1 — keys often start with "sk-api"
if os.getenv("MINIMAX_BASE_URL"):
    MINIMAX_BASE_URL = os.getenv("MINIMAX_BASE_URL").rstrip("/")
elif MINIMAX_API_KEY.startswith("sk-api"):
    MINIMAX_BASE_URL = "https://api.minimax.chat/v1"
else:
    MINIMAX_BASE_URL = "https://api.minimax.io/v1"

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

HEADERS = {
    "Authorization": f"Bearer {MINIMAX_API_KEY}",
    "Content-Type": "application/json",
}

# Shared HTTP session with default timeout
api_session = requests.Session()
api_session.headers.update(HEADERS)
api_session.timeout = 120


def validate_config():
    """Validate required configuration at startup."""
    import logging
    log = logging.getLogger("lincut")
    if not MINIMAX_API_KEY:
        log.error("MINIMAX_API_KEY not set. Copy .env.example to .env and add your key.")
        sys.exit(1)
    log.info("MiniMax API base URL: %s", MINIMAX_BASE_URL)

    missing = [cmd for cmd in ("ffmpeg", "ffprobe") if not shutil.which(cmd)]
    if missing:
        log.error(
            "%s not found in PATH. Install with: brew install ffmpeg "
            "(then restart the server so it picks up /opt/homebrew/bin)",
            ", ".join(missing),
        )
        sys.exit(1)
