#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgencyZoom SMS/Text API Probe (READ-ONLY)
- Authenticates and calls the texting-related endpoints:
  * POST /v1/api/text-thread/list              (paged; agent-agnostic)
  * POST /v1/api/text-thread/text-thread-detail (a sample of threadIds)
  * POST /v1/api/text-thread/producer          (meta/assignment info if available)
  * POST /v1/api/text-thread/unread-thread     (unread counts)
- Saves raw JSON responses + a concise summary to probe_out/

Env (set via Actions 'env:' or repo secrets):
  AZ_BASE                    (default: https://api.agencyzoom.com)
  AGENCY_ZOOM_USERNAME       (required)
  AGENCY_ZOOM_PASSWORD       (required)
  AGENCY_ZOOM_USER_ID        (optional; used for /producer if needed)
  PAGE_SIZE                  (default: 50)
  MAX_PAGES                  (default: 2)   # list pagination depth
  SAMPLE_THREADS             (default: 10)  # how many threadIds to detail
  FORCE_BACKFILL_MINUTES     (default: 10080)  # 7 days lookback if present
  SAVE_RAW_PER_PAGE          (0/1; default 1)  # write raw_api dumps
"""

from __future__ import annotations
import os, json, time, datetime, pathlib, typing
import requests

DEFAULT_AZ_BASE = "https://api.agencyzoom.com"

def env_int(k, d): 
    try: return int(os.getenv(k, str(d)))
    except: return d

def az_login(az_base, username, password):
    r = requests.post(f"{az_base}/v1/api/auth/login",
                      json={"username": username, "password": password}, timeout=30)
    r.raise_for_status()
    data = r.json()
    for k in ("token","accessToken","jwt"):
        if data.get(k): return data[k]
    return next(iter(data.values()))

def az_headers(tok): 
    return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

def http_with_retry(method, url, headers=None, json_body=None, max_reauth=1, token_ref=None, raw_path=None):
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = requests.request(method, url, headers=headers, json=json_body, timeout=45)
            # write raw if asked
            if raw_path:
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_text(resp.text)
            if resp.status_code in (401,403) and max_reauth > 0 and token_ref is not None:
                max_reauth -= 1
                token_ref["value"] = az_login(token_ref["base"], token_ref["user"], token_ref["pass"])
                if headers is not None:
                    headers.update(az_headers(token_ref["value"]))
                continue
            if resp.status_code == 429 and attempt <= 2:
                ra = resp.headers.get("Retry-After")
                wait_s = int(ra) if (ra and ra.isdigit()) else 60
                print(f"[429] {url} → waiting {wait_s}s")
                time.sleep(wait_s)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if isinstance(e, requests.HTTPError) and getattr(e, "response", None) and e.response.status_code == 429 and attempt <= 2:
                time.sleep(60)
                continue
            raise

def main():
    out = pathlib.Path("probe_out"); raw = out/"raw_api"
    out.mkdir(parents=True, exist_ok=True)

    az_base = os.getenv("AZ_BASE", DEFAULT_AZ_BASE)
    if not az_base.startswith("http"): az_base = DEFAULT_AZ_BASE

    user = os.getenv("AGENCY_ZOOM_USERNAME")
    pw   = os.getenv("AGENCY_ZOOM_PASSWORD")
    if not user or not pw:
        raise SystemExit("Missing AGENCY_ZOOM_USERNAME / AGENCY_ZOOM_PASSWORD")

    PAGE_SIZE       = env_int("PAGE_SIZE", 50)
    MAX_PAGES       = env_int("MAX_PAGES", 2)
    SAMPLE_THREADS  = env_int("SAMPLE_THREADS", 10)
    FB_MIN          = env_int("FORCE_BACKFILL_MINUTES", 10080)
    SAVE_RAW        = os.getenv("SAVE_RAW_PER_PAGE", "1") in {"1","true","yes","on"}
    USER_ID         = os.getenv("AGENCY_ZOOM_USER_ID")

    token_ref = {"value": None, "base": az_base, "user": user, "pass": pw}
    token_ref["value"] = az_login(az_base, user, pw)
    H = az_headers(token_ref["value"])

    # Prepare list payload (ALL agents; read-only)
    body_list = {"page": 1, "pageSize": PAGE_SIZE}
    # lookback cursor if provided
    if FB_MIN and FB_MIN > 0:
        start = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=FB_MIN)
        body_list["lastDateUTC"] = start.isoformat()

    # 1) text-thread/list (paged)
    threads = []
    for p in range(1, MAX_PAGES+1):
        body_list["page"] = p
        raw_path = raw/f"list_page_{p}.json" if SAVE_RAW else None
        r = http_with_retry("POST", f"{az_base}/v1/api/text-thread/list",
                            headers=H, json_body=body_list, token_ref=token_ref, raw_path=raw_path)
        j = r.json()
        items = j.get("items") or j.get("threads") or []
        print(f"list page {p}: {len(items)}")
        threads.extend(items)
        if not items: break

    (out/"list_threads.json").write_text(json.dumps(threads, ensure_ascii=False, indent=2))

    # determine sample thread ids to detail
    tids = []
    for th in threads:
        tid = str(th.get("threadId") or th.get("id") or "").strip()
        if tid and tid not in tids:
            tids.append(tid)
        if len(tids) >= SAMPLE_THREADS: break

    # 2) text-thread/text-thread-detail for sample threadIds
    details = {}
    for i, tid in enumerate(tids, 1):
        body = {"threadId": tid, "page": 1, "pageSize": 200}
        raw_path = raw/f"detail_{tid}.json" if SAVE_RAW else None
        r = http_with_retry("POST", f"{az_base}/v1/api/text-thread/text-thread-detail",
                            headers=H, json_body=body, token_ref=token_ref, raw_path=raw_path)
        details[tid] = r.json()
        print(f"detail {i}/{len(tids)}: {tid} → ok")
    (out/"details_by_thread.json").write_text(json.dumps(details, ensure_ascii=False, indent=2))

    # 3) text-thread/producer (if exposed; payloads vary by tenant—try safe defaults)
    prod_body = {"page": 1, "pageSize": PAGE_SIZE}
    if USER_ID: prod_body["agentSelect"] = str(USER_ID)
    try:
        raw_path = raw/"producer.json" if SAVE_RAW else None
        r = http_with_retry("POST", f"{az_base}/v1/api/text-thread/producer",
                            headers=H, json_body=prod_body, token_ref=token_ref, raw_path=raw_path)
        producer_json = r.json()
    except requests.HTTPError as e:
        producer_json = {"error": str(e), "status": getattr(e.response, "status_code", None), "text": getattr(e.response, "text", "")}
        print("producer call failed (non-fatal)")
    (out/"producer.json").write_text(json.dumps(producer_json, ensure_ascii=False, indent=2))

    # 4) text-thread/unread-thread (unread counters/ids)
    try:
        raw_path = raw/"unread_thread.json" if SAVE_RAW else None
        r = http_with_retry("POST", f"{az_base}/v1/api/text-thread/unread-thread",
                            headers=H, json_body={"page": 1, "pageSize": PAGE_SIZE},
                            token_ref=token_ref, raw_path=raw_path)
        unread_json = r.json()
    except requests.HTTPError as e:
        unread_json = {"error": str(e), "status": getattr(e.response, "status_code", None), "text": getattr(e.response, "text", "")}
        print("unread-thread call failed (non-fatal)")
    (out/"unread_thread.json").write_text(json.dumps(unread_json, ensure_ascii=False, indent=2))

    # Summary rollup
    summary = {
        "base": az_base,
        "pages_listed": min(MAX_PAGES, max(1, len(threads)//max(PAGE_SIZE,1)+1)),
        "threads_found": len(threads),
        "thread_ids_sampled": tids,
        "details_sampled": len(details),
        "has_producer_data": "error" not in producer_json,
        "has_unread_data": "error" not in unread_json,
        "params": {
            "PAGE_SIZE": PAGE_SIZE,
            "MAX_PAGES": MAX_PAGES,
            "SAMPLE_THREADS": SAMPLE_THREADS,
            "FORCE_BACKFILL_MINUTES": FB_MIN,
            "SAVE_RAW_PER_PAGE": int(SAVE_RAW),
        },
    }
    (out/"_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
