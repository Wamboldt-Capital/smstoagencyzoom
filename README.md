 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/README.md b/README.md
index 8b137891791fe96927ad78e64b0aad7bded08bdc..81d916a9011f69942a74c304f83738bd551952ac 100644
--- a/README.md
+++ b/README.md
@@ -1 +1,77 @@
+# AgencyZoom Utilities
 
+This repository contains small utilities for working with AgencyZoom data. The most actively maintained tool is `sms_to_todoist.py`, which reads SMS conversations from AgencyZoom and creates matching tasks in Todoist so you can triage new messages from your task list.
+
+## Prerequisites
+
+1. **Python 3.10+** – any recent CPython works.
+2. **Dependencies** – install the requirements into your environment:
+   ```bash
+   python -m venv .venv
+   source .venv/bin/activate
+   pip install -r requirements.txt
+   ```
+3. **AgencyZoom credentials** – a username and password with access to the SMS inbox.
+4. **Todoist REST API token** – create one from Todoist settings.
+
+## Configuration
+
+`sms_to_todoist.py` reads configuration from environment variables. The easiest approach is to create a local `.env` file in the repository root (the script loads it automatically at startup) with the following content:
+
+```dotenv
+# Required
+AGENCY_ZOOM_USERNAME=your_username
+AGENCY_ZOOM_PASSWORD=your_password
+TODOIST_API_TOKEN=your_token
+
+# Optional tweaks
+TODOIST_PROJECT_ID=1234567890   # send tasks to a specific project instead of the inbox
+AZ_THREADS_PAGE_SIZE=5          # number of SMS threads to fetch on each run
+AZ_MSGS_PAGE_SIZE=5             # number of messages pulled per thread
+AZ_ONLY_UNREAD=false            # reserved flag for future filtering
+AZ_SINCE_ISO=                   # ISO-8601 timestamp to only sync messages after this datetime
+DRY_RUN=false                   # set to true to preview without creating Todoist tasks
+DEBUG=false                     # set to true to print redacted request/response info
+```
+
+> **Note:** The script maintains an idempotency cache in `.sms_to_todoist_cache.json` so the same message is not turned into a task twice. You can delete the file if you ever need to resync everything from scratch.
+
+## Running the sync
+
+Once the environment variables are in place you can run the script directly:
+
+```bash
+python sms_to_todoist.py
+```
+
+For a dry run that shows which tasks would be created without contacting Todoist:
+
+```bash
+DRY_RUN=true python sms_to_todoist.py
+```
+
+To enable verbose debugging (request/response previews with sensitive data redacted):
+
+```bash
+DEBUG=true python sms_to_todoist.py
+```
+
+When you are satisfied with the automation you can schedule the command (for example with cron or a task runner) to keep Todoist in sync automatically.
+
+## Troubleshooting
+
+- If you see `AgencyZoom unauthorized; check username/password`, double-check the credentials in the environment or `.env` file.
+- Network issues are surfaced with `[error]` messages that include a short snippet of the upstream response to help with debugging.
+- Increase `REQUEST_TIMEOUT_SECONDS` in the environment if AgencyZoom or Todoist is slow to respond from your network.
+
+## Other utilities
+
+The repository also contains legacy scripts retained for reference:
+
+- `sync_agency_zoom_todoist.py`
+- `az_sms_todoist_teams.py`
+- `az_sms_todoist_teams_flat.py`
+- `debug_api_structure.py`
+- `updated export_contacts.py`
+
+They are not actively maintained but remain available if you still rely on them.
 
EOF
)
