#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgencyZoom SMS Debug Dumper (read-only)
--------------------------------------
Pulls *all available fields* for recent text threads + messages and writes
machine-friendly artifacts for inspection.

Outputs (default to ./debug_out):
  - debug_out/threads.json                (raw thread objects)
  - debug_out/messages.json               (raw flattened message records)
  - debug_out/messages.jsonl              (one JSON object per line)
  - debug_out/chat_refs_debug.jsonl       (minimal schema keyed by thread_id)
  - debug_out/_sample_keys.txt            (observed keys for thread/message)
  - debug_out/_run.log                    (summary counts and params)
  - optional: debug_out/raw_api/*         (per-page raw API responses)

Environment variables (read via os.getenv):
  AZ_BASE                      (default: https://api.agencyzoom.com)
  AGENCY_ZOOM_USERNAME         (required)
  AGENCY_ZOOM_PASSWORD         (required)
  AGENCY_ZOOM_USER_ID          (optional; only needed if TEXT_FILTER_MODE=mine)
  TEXT_FILTER_MODE             (default: all)  # all | mine
  FORCE_BACKFILL_MINUTES       (default: 10080 → ~7 days)
  LIMIT_THREADS                (default: 200)
  LIMIT_MSGS_PER_THREAD        (default: 50)
  TOTAL_LIMIT                  (default: 50)   # global newest messages cap
  OUTPUT_DIR                   (default: debug_out)
  SAVE_RAW_PER_PAGE            (default: 0)    # set to 1 to save raw API pages

Usage (GitHub Actions env):
  TEXT_FILTER_MODE=all TOTAL_LIMIT=50 FORCE_BACKFILL_MINUTES=10080 python az_sms_debug_dump.py

Notes:
- Retries once on HTTP 429 (honors Retry-After when present; fallback 60s).
- Re-auths once on 401/403.
- No writes/mutations to AgencyZoom; read-only calls.
"""

from __future__ import annotations
import os
import sys
import json
import time
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests

DEFAULT_AZ_BASE = "https://api.agencyzoom.com"

# ---------------------------
# ENV HELPERS
# ---------------------------
def env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name, "")
    if v == "":
        return default
    return v.lower() in {"1", "true", "yes", "y", "on"}

def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default

# ---------------------------
# AZ AUTH / HTTP
# ---------------------------
def az_login(az_base: str, username: str, password: str) -> str:
    url = f"{az_base}/v1/api/auth/login"
    r = requests.post(url, json={"username": username, "password": password}, timeout=30)
    r.raise_for_status()
    data = r.json()
    for k in ("token", "accessToken", "jwt"):
        if data.get(k):
            return data[k]
    # fallback to first value if unknown shape
    return next(iter(data.values()))

def az_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def http_with_retry(method: str, url: str, *, headers: Dict[str, str], json_body: Optional[dict],
                    token_getter, max_reauth: int = 1, raw_path: Optional[Path] = None):
    """
    Makes an HTTP request with:
      - single re-auth retry on 401/403
      - single 429 retry (uses Retry-After or 60s)
      - optional raw response dump to file
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = requests.request(method, url, headers=headers, json=json_body, timeout=45)
            if raw_path is not None:
                try:
                    raw_path.parent.mkdir(parents=True, exist_ok=True)
                    raw_path.write_text(resp.text)
                except Exception:
                    pass

            if resp.status_code in (401, 403) and max_reauth > 0:
                # refresh token and retry once
                max_reauth -= 1
                new_tok = token_getter(refresh=True)
                headers.clear()
                headers.update(az_headers(new_tok))
                continue

            if resp.status_code == 429 and attempt <= 2:
                ra = resp.headers.get("Retry-After")
                wait_s = int(ra) if (ra and ra.isdigit()) else 60
                print(f"[429] {url} → waiting {wait_s}s then retrying…")
                time.sleep(wait_s)
                continue

            resp.raise_for_status()
            return resp

        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 429 and attempt <= 2:
                time.sleep(60)
                continue
            raise

# ---------------------------
# API CALLS
# ---------------------------
def list_text_threads(az_base: str, token_getter, mode: str, user_id: Optional[str],
                      last_date_utc: Optional[str], limit_threads: int,
                      save_raw_pages: bool, raw_dir: Path) -> List[Dict[str, Any]]:
    url = f"{az_base}/v1/api/text-thread/list"
    threads: List[Dict[str, Any]] = []
    page = 1
    page_size = 100  # server may clamp to 50; that's fine

    headers = az_headers(token_getter(refresh=False))

    while True:
        body = {"page": page, "pageSize": page_size}
        if mode == "mine" and user_id:
            body["agentSelect"] = str(user_id)
        if last_date_utc:
            body["lastDateUTC"] = last_date_utc

        raw_path = (raw_dir / f"threads_page_{page}.json") if save_raw_pages else None
        resp = http_with_retry("POST", url, headers=headers, json_body=body,
                               token_getter=token_getter, raw_path=raw_path)
        j = resp.json()
        items = j.get("items") or j.get("threads") or []
        if not items:
            break

        threads.extend(items)
        print(f"  fetched threads page {page} → {len(items)} items (total {len(threads)})")

        if len(threads) >= limit_threads:
            threads = threads[:limit_threads]
            break
        page += 1

    return threads

def thread_detail_messages(az_base: str, token_getter, thread_id: str,
                           save_raw_pages: bool, raw_dir: Path, limit_msgs: int) -> List[Dict[str, Any]]:
    url = f"{az_base}/v1/api/text-thread/text-thread-detail"
    messages: List[Dict[str, Any]] = []
    page = 1
    page_size = 200
    headers = az_headers(token_getter(refresh=False))

    while True:
        body = {"threadId": thread_id, "page": page, "pageSize": page_size}
        raw_path = (raw_dir / f"thread_{thread_id}_page_{page}.json") if save_raw_pages else None
        resp = http_with_retry("POST", url, headers=headers, json_body=body,
                               token_getter=token_getter, raw_path=raw_path)
        j = resp.json()
        items = j.get("items") or j.get("messages") or []
        if not items:
            break

        messages.extend(items)
        if len(messages) >= limit_msgs:
            messages = messages[:limit_msgs]
            break

        page += 1

    return messages

# ---------------------------
# UTIL
# ---------------------------
def iso_to_dt(s: Optional[str]) -> Optional[datetime.datetime]:
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None

def collect_keys(records: List[Dict[str, Any]]) -> List[str]:
    seen = set()
    for r in records:
        for k in r.keys():
            seen.add(k)
    return sorted(seen)

# ---------------------------
# MAIN
# ---------------------------
def main():
    out_dir = Path(os.getenv("OUTPUT_DIR", "debug_out"))
    raw_dir = out_dir / "raw_api"
    out_dir.mkdir(parents=True, exist_ok=True)

    az_base = os.getenv("AZ_BASE", DEFAULT_AZ_BASE)
    if not az_base.startswith("http"):
        az_base = DEFAULT_AZ_BASE

    username = os.getenv("AGENCY_ZOOM_USERNAME")
    password = os.getenv("AGENCY_ZOOM_PASSWORD")
    if not username or not password:
        print("ERROR: Set AGENCY_ZOOM_USERNAME and AGENCY_ZOOM_PASSWORD in the environment.", file=sys.stderr)
        sys.exit(2)

    text_filter_mode = (os.getenv("TEXT_FILTER_MODE", "all") or "all").lower()
    force_backfill_minutes = env_int("FORCE_BACKFILL_MINUTES", 10080)
    limit_threads = env_int("LIMIT_THREADS", 200)
    limit_msgs_per_thread = env_int("LIMIT_MSGS_PER_THREAD", 50)
    total_limit = env_int("TOTAL_LIMIT", 50)
    save_raw_per_page = env_bool("SAVE_RAW_PER_PAGE", False)
    user_id = os.getenv("AGENCY_ZOOM_USER_ID")

    # token getter with lazy refresh
    _token_cache = {"value": None}
    def token_getter(refresh: bool = False) -> str:
        if refresh or not _token_cache["value"]:
            _token_cache["value"] = az_login(az_base, username, password)
        return _token_cache["value"]

    # cursor/backfill window
    last_date_utc: Optional[str] = None
    if force_backfill_minutes and force_backfill_minutes > 0:
        start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=force_backfill_minutes)
        last_date_utc = start.isoformat()
        print(f"[INFO] Backfill window set → lastDateUTC={last_date_utc}")

    # mine-mode sanity
    if text_filter_mode == "mine" and not user_id:
        print("[WARN] TEXT_FILTER_MODE=mine but AGENCY_ZOOM_USER_ID is not set. Falling back to 'all'.")
        text_filter_mode = "all"

    # 1) List threads
    print(f"[RUN] Listing threads… base={az_base} mode={text_filter_mode} limit_threads={limit_threads}")
    threads = list_text_threads(
        az_base=az_base,
        token_getter=token_getter,
        mode=text_filter_mode,
        user_id=user_id,
        last_date_utc=last_date_utc,
        limit_threads=limit_threads,
        save_raw_pages=save_raw_per_page,
        raw_dir=raw_dir,
    )
    (out_dir / "threads.json").write_text(json.dumps(threads, ensure_ascii=False, indent=2))

    # 2) Pull messages per thread
    flat_msgs: List[Dict[str, Any]] = []
    for i, th in enumerate(threads, 1):
        tid = str(th.get("threadId") or th.get("id") or "").strip()
        print(f"  [{i}/{len(threads)}] Messages for thread {tid or '(unknown)'}")
        msgs = thread_detail_messages(
            az_base=az_base,
            token_getter=token_getter,
            thread_id=tid,
            save_raw_pages=save_raw_per_page,
            raw_dir=raw_dir,
            limit_msgs=limit_msgs_per_thread,
        )
        for m in msgs:
            flat_msgs.append({
                "thread_id": tid,
                "thread": th,
                "message": m,
                # derived helpers
                "thread_contact": th.get("contactName") or th.get("leadName") or th.get("customerName"),
                "direction": m.get("direction") or m.get("fromRole"),
                "sent_at": m.get("sentAt") or m.get("createdAt") or m.get("dateUtc") or m.get("date"),
            })

    # 3) Global newest-N trim (TOTAL_LIMIT)
    if total_limit and total_limit > 0:
        def key_ts(rec: Dict[str, Any]):
            dt = iso_to_dt(rec.get("sent_at"))
            # put None at the very beginning
            return dt or datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
        flat_msgs.sort(key=key_ts, reverse=True)
        if len(flat_msgs) > total_limit:
            flat_msgs = flat_msgs[:total_limit]

    # 4) Write outputs
    (out_dir / "messages.json").write_text(json.dumps(flat_msgs, ensure_ascii=False, indent=2))
    with (out_dir / "messages.jsonl").open("w", encoding="utf-8") as f:
        for rec in flat_msgs:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    with (out_dir / "chat_refs_debug.jsonl").open("w", encoding="utf-8") as f:
        for rec in flat_msgs:
            th = rec["thread"]; m = rec["message"]
            tid = rec["thread_id"]
            lead = rec.get("thread_contact") or m.get("fromName") or m.get("senderName") or "Unknown"
            body = m.get("body") or m.get("message") or m.get("text") or ""
            f.write(json.dumps({
                "thread_id": tid,
                "chat_ref": tid,
                "lead": lead,
                "sent_at": rec.get("sent_at"),
                "direction": rec.get("direction"),
                "message": body,
            }, ensure_ascii=False) + "\n")

    thread_keys = collect_keys(threads)
    msg_keys = collect_keys([rec["message"] for rec in flat_msgs])

    with (out_dir / "_sample_keys.txt").open("w", encoding="utf-8") as f:
        f.write("[THREAD KEYS]\n")
        for k in thread_keys: f.write(f"- {k}\n")
        f.write("\n[MESSAGE KEYS]\n")
        for k in msg_keys: f.write(f"- {k}\n")

    total_msgs = len(flat_msgs)
    example_ts = next((rec.get("sent_at") for rec in flat_msgs if rec.get("sent_at")), None)
    with (out_dir / "_run.log").open("w", encoding="utf-8") as f:
        f.write(f"threads: {len(threads)}\n")
        f.write(f"messages: {total_msgs}\n")
        f.write(f"example_sent_at: {example_ts}\n")
        f.write(f"mode: {text_filter_mode}\n")
        f.write(f"lastDateUTC: {last_date_utc}\n")
        f.write(f"TOTAL_LIMIT: {total_limit}\n")
        f.write(f"LIMIT_THREADS: {limit_threads}\n")
        f.write(f"LIMIT_MSGS_PER_THREAD: {limit_msgs_per_thread}\n")

    print("\n[SUMMARY]")
    print(f"  Threads:  {len(threads)}  → { (out_dir / 'threads.json') }")
    print(f"  Messages: {total_msgs}    → { (out_dir / 'messages.json') } / { (out_dir / 'messages.jsonl') }")
    print(f"  ChatRefs:                 → { (out_dir / 'chat_refs_debug.jsonl') }")
    print(f"  Keys inventory:           → { (out_dir / '_sample_keys.txt') }")
    print(f"  Run log:                  → { (out_dir / '_run.log') }")
    if save_raw_per_page:
        print(f"  Raw API pages:            → { raw_dir }")

if __name__ == "__main__":
    main()
