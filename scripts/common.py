"""Shared helpers: paths, Taipei time, cache read/write with fallback."""
import json
import os
from datetime import datetime, timezone, timedelta

TAIPEI = timezone(timedelta(hours=8))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
STATE_DIR = os.path.join(DATA_DIR, "state")

for d in (RAW_DIR, CACHE_DIR, STATE_DIR):
    os.makedirs(d, exist_ok=True)


def now_taipei():
    return datetime.now(TAIPEI)


def log(msg):
    ts = now_taipei().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def fetch_with_cache_fallback(fetch_fn, cache_name, *, label=""):
    """Run fetch_fn(); on failure, fall back to the last cached JSON so the
    page never shows a blank section just because one source is down."""
    cache_path = os.path.join(CACHE_DIR, cache_name)
    try:
        result = fetch_fn()
        if result is not None:
            save_json(cache_path, {"fetched_at": now_taipei().isoformat(), "data": result})
            return result, False
        raise ValueError("fetch_fn returned None")
    except Exception as e:
        log(f"WARN {label or cache_name}: fetch failed ({e}), falling back to cache")
        cached = load_json(cache_path)
        if cached:
            return cached["data"], True
        log(f"ERROR {label or cache_name}: no cache available either, skipping section")
        return None, True
