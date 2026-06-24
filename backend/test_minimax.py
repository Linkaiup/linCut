"""Test MiniMax API connectivity: video generation, TTS, and music."""
import os
import sys
import json
import time
import requests

from backend.config import MINIMAX_API_KEY, MINIMAX_BASE_URL, HEADERS

API_KEY = MINIMAX_API_KEY


def test_tts():
    """Test TTS API (synchronous, fastest to verify)."""
    print("\n=== Testing TTS (Speech-2.6-HD) ===")
    url = f"{MINIMAX_BASE_URL}/t2a_v2"
    payload = {
        "model": "speech-2.6-hd",
        "text": "Welcome to linCut, your AI film crew.",
        "stream": False,
        "voice_setting": {
            "voice_id": "English_expressive_narrator",
            "speed": 1,
            "vol": 1,
            "pitch": 0,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "bitrate": 128000,
            "format": "mp3",
            "channel": 1,
        },
    }
    resp = requests.post(url, headers=HEADERS, json=payload)
    if resp.status_code != 200:
        print(f"FAIL: status={resp.status_code}, body={resp.text[:500]}")
        return False

    data = resp.json()
    if "data" in data and "audio" in data["data"]:
        audio_bytes = bytes.fromhex(data["data"]["audio"])
        out_path = os.path.join(os.path.dirname(__file__), "output", "test_tts.mp3")
        with open(out_path, "wb") as f:
            f.write(audio_bytes)
        print(f"OK: saved {len(audio_bytes)} bytes to {out_path}")
        return True
    else:
        print(f"FAIL: unexpected response: {json.dumps(data, indent=2)[:500]}")
        return False


def test_video_create():
    """Test video generation task creation (does not wait for completion)."""
    print("\n=== Testing Video Generation (Hailuo) ===")
    url = f"{MINIMAX_BASE_URL}/video_generation"
    payload = {
        "prompt": "A futuristic city skyline at sunset with flying cars and neon lights, cinematic style, smooth camera pan from left to right.",
        "model": "MiniMax-Hailuo-2.3",
        "duration": 6,
        "resolution": "1080P",
    }
    resp = requests.post(url, headers=HEADERS, json=payload)
    if resp.status_code != 200:
        print(f"FAIL: status={resp.status_code}, body={resp.text[:500]}")
        return None

    data = resp.json()
    task_id = data.get("task_id")
    if task_id:
        print(f"OK: task_id={task_id}")
        return task_id
    else:
        print(f"FAIL: no task_id in response: {json.dumps(data, indent=2)[:500]}")
        return None


def poll_video(task_id, max_wait=300):
    """Poll video generation status until done."""
    print(f"\n=== Polling Video Task {task_id} ===")
    url = f"{MINIMAX_BASE_URL}/query/video_generation"
    start = time.time()
    while time.time() - start < max_wait:
        time.sleep(10)
        resp = requests.get(url, headers=HEADERS, params={"task_id": task_id})
        data = resp.json()
        status = data.get("status", "Unknown")
        print(f"  status={status} ({int(time.time()-start)}s elapsed)")
        if status == "Success":
            return data.get("file_id")
        elif status == "Fail":
            print(f"  FAIL: {data.get('error_message', 'unknown error')}")
            return None
    print(f"  TIMEOUT after {max_wait}s")
    return None


def download_video(file_id):
    """Download video by file_id."""
    print(f"\n=== Downloading Video (file_id={file_id}) ===")
    url = f"{MINIMAX_BASE_URL}/files/retrieve"
    resp = requests.get(url, headers=HEADERS, params={"file_id": file_id})
    data = resp.json()
    download_url = data.get("file", {}).get("download_url")
    if not download_url:
        print(f"FAIL: no download_url: {json.dumps(data, indent=2)[:500]}")
        return False

    video_resp = requests.get(download_url)
    out_path = os.path.join(os.path.dirname(__file__), "output", "test_video.mp4")
    with open(out_path, "wb") as f:
        f.write(video_resp.content)
    print(f"OK: saved {len(video_resp.content)} bytes to {out_path}")
    return True


if __name__ == "__main__":
    if not API_KEY:
        print("ERROR: MINIMAX_API_KEY not set in .env")
        sys.exit(1)

    print(f"API Key: {API_KEY[:10]}...{API_KEY[-4:]}")
    print(f"Base URL: {MINIMAX_BASE_URL}")

    # Test 1: TTS (fast, synchronous)
    tts_ok = test_tts()

    # Test 2: Video generation (async, takes a few minutes)
    task_id = test_video_create()
    if task_id:
        file_id = poll_video(task_id)
        if file_id:
            download_video(file_id)

    print("\n=== Summary ===")
    print(f"TTS: {'PASS' if tts_ok else 'FAIL'}")
    print(f"Video: {'task created' if task_id else 'FAIL'}")
