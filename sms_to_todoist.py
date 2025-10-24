"""Pull recent SMS threads from AgencyZoom and create Todoist tasks."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import requests
from requests import RequestException
from requests import Response
from requests.exceptions import HTTPError

AZ_BASE = (os.getenv("AZ_BASE") or "https://api.agencyzoom.com").rstrip("/")
AZ_API_BASE = f"{AZ_BASE}/v1"
CACHE_FILE = ".sms_to_todoist_cache.json"
OUTPUT_FILE = os.getenv("SMS_OUTPUT_FILE", "sms_messages.txt")
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT_SECONDS") or "30")
DEFAULT_ENV_FILE = ".env"


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y"}


DEBUG_MODE = _bool_env("DEBUG", False)


# -------- helpers ---------


def load_env_file(path: str = DEFAULT_ENV_FILE) -> None:
    """Populate environment variables from a local ``.env`` style file."""

    if not path:
        return

    try:
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue

                if "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                if not key:
                    continue

                value = value.strip().strip('"').strip("'")
                os.environ.setdefault(key, value)
    except FileNotFoundError:
        return
    except Exception as exc:  # pragma: no cover - defensive logging only
        print(f"[warn] failed to parse env file {path}: {exc}")


def debug(message: str) -> None:
    if DEBUG_MODE:
        print(f"[debug] {message}")


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def load_cache() -> set[str]:
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except FileNotFoundError:
        return set()
    except Exception:
        return set()
    seen: Iterable[str] = payload.get("seen_message_ids", []) if isinstance(payload, dict) else []
    return {str(item) for item in seen}


def save_cache(ids: Iterable[str]) -> None:
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as fh:
            json.dump({"seen_message_ids": sorted({str(i) for i in ids})}, fh, indent=2)
    except Exception as exc:  # pragma: no cover - best effort logging
        print(f"[warn] failed to write cache: {exc}")


def parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        # AgencyZoom returns strings like "2023-10-08T16:14:23.123Z"
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# -------- AgencyZoom --------

def _redact_payload(payload: dict[str, Any], fields: set[str]) -> dict[str, Any]:
    if not fields:
        return payload
    sanitized: dict[str, Any] = {}
    for key, value in payload.items():
        sanitized[key] = "***" if key in fields else value
    return sanitized


def _post_json(
    url: str,
    *,
    payload: dict[str, Any],
    headers: Optional[dict[str, str]] = None,
    redact_fields: Optional[Iterable[str]] = None,
) -> Response:
    if redact_fields:
        debug(f"POST {url} payload={_redact_payload(payload, set(redact_fields))}")
    else:
        debug(f"POST {url} payload={payload}")
    if headers:
        redacted_headers = {k: ("***" if k.lower() == "authorization" else v) for k, v in headers.items()}
        debug(f"POST headers={redacted_headers}")
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    except RequestException as exc:  # pragma: no cover - network failure logging
        raise RuntimeError(f"HTTP request to {url} failed: {exc}") from exc
    debug(f"response status={response.status_code}")
    if DEBUG_MODE:
        body_preview = response.text[:500]
        debug(f"response body preview={body_preview!r}")
    return response


def _raise_for_status(response: Response, context: str) -> None:
    try:
        response.raise_for_status()
    except HTTPError as exc:
        snippet = (response.text or "").strip()
        if len(snippet) > 800:
            snippet = snippet[:800] + "…"
        raise RuntimeError(f"{context} failed with status {response.status_code}: {snippet}") from exc


def _json_or_error(response: Response, context: str) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError as exc:
        snippet = (response.text or "").strip()
        if len(snippet) > 800:
            snippet = snippet[:800] + "…"
        raise RuntimeError(f"{context} returned invalid JSON: {snippet}") from exc
    if isinstance(data, dict):
        return data
    if isinstance(data, list):
        return {"items": data}
    raise RuntimeError(f"{context} returned unexpected payload type: {type(data)!r}")


def az_login(username: str, password: str) -> str:
    url = f"{AZ_API_BASE}/api/auth/login"
    payload = {"username": username, "password": password}
    print(f"[az] logging in as {username} …")
    response = _post_json(url, payload=payload, redact_fields={"password"})
    print(f"[az] login status={response.status_code}")
    if response.status_code == 401:
        raise RuntimeError("AgencyZoom unauthorized; check username/password")
    _raise_for_status(response, "AgencyZoom login")
    data = _json_or_error(response, "AgencyZoom login")
    token = (
        data.get("jwt_token")
        or data.get("jwt")
        or data.get("token")
        or data.get("accessToken")
    )
    if not token:
        # Some responses use a single key with the token value
        if len(data) == 1:
            token = next(iter(data.values()))
    if not token:
        raise RuntimeError("No token field found in AgencyZoom login response")
    return str(token)


def az_get_threads(token: str, page_size: int) -> list[dict[str, Any]]:
    url = f"{AZ_API_BASE}/api/text-thread/list"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"pageSize": page_size, "page": 0, "sort": "lastMessageDate", "order": "desc"}
    print(f"[az] fetching threads page_size={page_size} …")
    response = _post_json(url, payload=payload, headers=headers)
    print(f"[az] threads status={response.status_code}")
    if response.status_code == 401:
        raise RuntimeError("AgencyZoom unauthorized; token rejected")
    _raise_for_status(response, "AgencyZoom threads")
    data = _json_or_error(response, "AgencyZoom threads")
    threads = data.get("threadInfo") or data.get("items") or data.get("threads")
    return threads or []


def az_get_messages(token: str, thread_id: str, page_size: int) -> list[dict[str, Any]]:
    url = f"{AZ_API_BASE}/api/text-thread/text-thread-detail"
    headers = {"Authorization": f"Bearer {token}"}
    payload = {"threadId": thread_id, "pageSize": page_size, "page": 0}
    print(f"[az] fetching messages thread_id={thread_id} page_size={page_size} …")
    response = _post_json(url, payload=payload, headers=headers)
    print(f"[az] messages status={response.status_code}")
    _raise_for_status(response, "AgencyZoom messages")
    data = _json_or_error(response, "AgencyZoom messages")
    messages = data.get("messageInfo") or data.get("items") or data.get("messages")
    return messages or []


# -------- Todoist --------

def todoist_create_task(token: str, content: str, project_id: Optional[str] = None) -> dict[str, Any]:
    url = "https://api.todoist.com/rest/v2/tasks"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload: dict[str, Any] = {"content": content}
    if project_id:
        payload["project_id"] = project_id

    response = _post_json(url, payload=payload, headers=headers)
    print(f"[todoist] create status={response.status_code}")
    if response.status_code in {429, 500, 502, 503, 504}:
        wait_seconds = int(response.headers.get("Retry-After", "2"))
        print(f"[todoist] retrying after {wait_seconds}s …")
        time.sleep(wait_seconds)
        response = _post_json(url, payload=payload, headers=headers)
        print(f"[todoist] retry status={response.status_code}")
    _raise_for_status(response, "Todoist create task")
    if not response.text:
        return {}
    try:
        result = response.json()
        if result.get("id"):
            print(f"[todoist] task created: {result['id']}")
        return result
    except ValueError:
        return {}


# -------- main flow --------

def main() -> None:
    load_env_file()

    username = os.getenv("AGENCY_ZOOM_USERNAME")
    password = os.getenv("AGENCY_ZOOM_PASSWORD")
    todoist_token = os.getenv("TODOIST_API_TOKEN")
    project_id = os.getenv("TODOIST_PROJECT_ID")

    missing = []
    if not username:
        missing.append("AGENCY_ZOOM_USERNAME")
    if not password:
        missing.append("AGENCY_ZOOM_PASSWORD")
    if not todoist_token:
        missing.append("TODOIST_API_TOKEN")

    if missing:
        missing_s = ", ".join(missing)
        raise SystemExit(
            "Missing required configuration: "
            f"{missing_s}. Set environment variables or add them to {DEFAULT_ENV_FILE}."
        )

    threads_page = _int_env("AZ_THREADS_PAGE_SIZE", 5)
    msgs_page = _int_env("AZ_MSGS_PAGE_SIZE", 5)
    dry_run = _bool_env("DRY_RUN", False)
    inbound_only = _bool_env("AZ_INBOUND_ONLY", False)
    since_iso = os.getenv("AZ_SINCE_ISO", "").strip()
    since_dt = parse_iso(since_iso) if since_iso else None

    token = az_login(username, password)
    threads = az_get_threads(token, threads_page)
    print(f"[az] threads fetched: {len(threads)}")
    if inbound_only:
        print("[filter] inbound messages only (skipping outbound)")

    seen_ids = load_cache()
    new_seen = set(seen_ids)
    created_count = 0
    skipped_count = 0
    all_messages = []  # Collect messages for text file export

    for thread in threads:
        thread_id = str(thread.get("id") or thread.get("threadId") or "")
        if not thread_id:
            continue
        contact_name = thread.get("contactName") or thread.get("leadName") or "Unknown"
        for message in az_get_messages(token, thread_id, msgs_page):
            message_id = str(message.get("id") or message.get("messageId") or "")
            if not message_id:
                continue
            if message_id in seen_ids:
                skipped_count += 1
                continue

            message_date_raw = message.get("messageDate") or message.get("sentDate") or ""
            message_dt = parse_iso(message_date_raw)
            if since_dt and message_dt and message_dt < since_dt:
                skipped_count += 1
                continue

            body = (message.get("body") or message.get("message") or "").strip()
            sender = message.get("senderName") or message.get("fromName") or "Unknown"

            # Filter for inbound messages only if requested
            if inbound_only:
                direction = message.get("direction", "").lower()
                msg_type = message.get("type", "").lower()
                is_inbound = message.get("inbound") or message.get("incoming") or message.get("fromCustomer")

                # Heuristic detection based on message content patterns
                body_lower = body.lower()

                # Common agent signatures in outbound messages
                agent_signatures = [
                    "jared ullrich", "noah", "luke murdoch", "luke", "carl",
                    "ullrich insurance", "- jared", "- noah", "- luke", "- carl"
                ]
                has_agent_signature = any(sig in body_lower for sig in agent_signatures)

                # Common outbound phrases (business speaking to customer)
                outbound_phrases = [
                    "our office", "our service team", "our team", "our insurance",
                    "dave ramsey", "endorsed local provider", "elp",
                    "call our office", "contact our office",
                    "ullrichinsurance.com", "www.ullrich"
                ]
                has_outbound_phrase = any(phrase in body_lower for phrase in outbound_phrases)

                # Common outbound greeting patterns
                first_name = contact_name.split()[0].lower() if contact_name != "Unknown" and contact_name else None
                outbound_greetings = []
                if first_name:
                    outbound_greetings = [
                        f"hey {first_name}", f"hi {first_name}",
                        f"hello {first_name}", f"hey {first_name}!"
                    ]
                has_outbound_greeting = any(body_lower.startswith(greeting) for greeting in outbound_greetings)

                # Debug: show what fields we're checking
                if DEBUG_MODE:
                    debug(f"Message {message_id}: direction={direction!r}, type={msg_type!r}, inbound={is_inbound!r}")
                    debug(f"  body preview: {body[:100]!r}")
                    debug(f"  has_agent_signature={has_agent_signature}, has_outbound_greeting={has_outbound_greeting}, has_outbound_phrase={has_outbound_phrase}")

                # Check multiple possible field formats
                is_outbound = (
                    direction in {"outbound", "out", "sent", "send"}
                    or msg_type in {"outbound", "out", "sent", "send"}
                    or is_inbound is False
                    or has_agent_signature  # Fallback: detect by agent signature
                    or has_outbound_greeting  # Fallback: detect by greeting pattern
                    or has_outbound_phrase  # Fallback: detect by business phrases
                )

                if is_outbound:
                    debug(f"Skipping outbound message {message_id}")
                    skipped_count += 1
                    continue
                else:
                    debug(f"Including inbound message {message_id}")

            date_label = message_date_raw or "unknown date"
            content = f"SMS on {date_label} from {sender} ({contact_name}): {body}"
            content = content[:990]  # keep under Todoist 1k char limit buffer
            print(f"[task] {content}")

            # Collect message details for text file export
            all_messages.append({
                "date": date_label,
                "sender": sender,
                "contact": contact_name,
                "body": body,
                "message_id": message_id
            })

            if not dry_run:
                todoist_create_task(todoist_token, content, project_id)
                created_count += 1

            new_seen.add(message_id)

    save_cache(new_seen)

    # Write messages to text file for easy reading
    if all_messages:
        try:
            with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
                f.write("=" * 80 + "\n")
                f.write("SMS MESSAGES EXPORT\n")
                f.write(f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
                f.write(f"Total Messages: {len(all_messages)}\n")
                f.write("=" * 80 + "\n\n")

                for idx, msg in enumerate(all_messages, 1):
                    f.write(f"MESSAGE #{idx}\n")
                    f.write("-" * 80 + "\n")
                    f.write(f"Date:    {msg['date']}\n")
                    f.write(f"From:    {msg['sender']}\n")
                    f.write(f"Contact: {msg['contact']}\n")
                    f.write(f"ID:      {msg['message_id']}\n")
                    f.write(f"\nMessage:\n{msg['body']}\n")
                    f.write("\n" + "=" * 80 + "\n\n")

            print(f"[file] exported {len(all_messages)} messages to {OUTPUT_FILE}")
        except Exception as exc:
            print(f"[warn] failed to write output file: {exc}")

    print(
        f"[done] tasks created={created_count}, "
        f"skipped={skipped_count}, cached_ids={len(new_seen)}"
    )


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as exc:
        raise SystemExit(f"[error] {exc}") from exc
