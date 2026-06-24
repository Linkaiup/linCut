"""Smoke-test MiniMax API connectivity."""
import sys

from backend.core.settings import MINIMAX_API_KEY, MINIMAX_BASE_URL, AUTH_HEADERS, bootstrap

bootstrap()

API_KEY = MINIMAX_API_KEY
HEADERS = AUTH_HEADERS


def test_tts():
    import requests

    print("\n=== TTS ===")
    url = f"{MINIMAX_BASE_URL}/t2a_v2"
    payload = {
        "model": "speech-2.6-hd",
        "text": "linCut is online.",
        "stream": False,
        "voice_setting": {"voice_id": "English_expressive_narrator", "speed": 1, "vol": 1, "pitch": 0},
        "audio_setting": {"sample_rate": 32000, "bitrate": 128000, "format": "mp3", "channel": 1},
    }
    resp = requests.post(url, headers=HEADERS, json=payload, timeout=60)
    data = resp.json()
    base = data.get("base_resp", {})
    if base.get("status_code", 0) != 0:
        print(f"FAIL: {base.get('status_msg')} (code {base.get('status_code')})")
        return False
    print("OK")
    return True


def test_video():
    import time
    import requests

    print("\n=== Video (Hailuo) ===")
    create_url = f"{MINIMAX_BASE_URL}/video_generation"
    payload = {
        "prompt": "A calm ocean at sunset, cinematic wide shot",
        "model": "MiniMax-Hailuo-2.3",
        "duration": 6,
        "resolution": "1080P",
    }
    resp = requests.post(create_url, headers=HEADERS, json=payload, timeout=120)
    data = resp.json()
    base = data.get("base_resp", {})
    if base.get("status_code", 0) != 0:
        print(f"FAIL: {base.get('status_msg')} (code {base.get('status_code')})")
        return False
    task_id = data.get("task_id")
    print(f"Task created: {task_id}")

    query_url = f"{MINIMAX_BASE_URL}/query/video_generation"
    for _ in range(30):
        time.sleep(10)
        q = requests.get(query_url, headers=HEADERS, params={"task_id": task_id}, timeout=30)
        status = q.json().get("status")
        print(f"  status: {status}")
        if status in ("Success", "Fail"):
            return status == "Success"
    print("TIMEOUT")
    return False


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: MINIMAX_API_KEY not set")
        sys.exit(1)
    print(f"Endpoint: {MINIMAX_BASE_URL}")
    ok = test_tts()
    sys.exit(0 if ok else 1)
