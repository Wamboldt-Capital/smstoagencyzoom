# AgencyZoom Utilities

This repository contains small utilities for working with AgencyZoom data. The most actively maintained tool is `sms_to_todoist.py`, which reads SMS conversations from AgencyZoom and creates matching tasks in Todoist so you can triage new messages from your task list.

## Prerequisites

1. **Python 3.10+** – any recent CPython works.
2. **Dependencies** – install the requirements into your environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **AgencyZoom credentials** – a username and password with access to the SMS inbox.
4. **Todoist REST API token** – create one from Todoist settings.

## Configuration

`sms_to_todoist.py` reads configuration from environment variables. The easiest approach is to create a local `.env` file in the repository root (the script loads it automatically at startup) with the following content:

```dotenv
# Required
AGENCY_ZOOM_USERNAME=your_username
AGENCY_ZOOM_PASSWORD=your_password
TODOIST_API_TOKEN=your_token

# Optional tweaks
TODOIST_PROJECT_ID=inbound-messages-6f7xhQPJr6vFXFhc   # send tasks to a specific project
TODOIST_SECTION_ID=123456789    # send tasks to a specific section within the project
AZ_THREADS_PAGE_SIZE=5          # number of SMS threads to fetch on each run
AZ_MSGS_PAGE_SIZE=5             # number of messages pulled per thread
AZ_INBOUND_ONLY=true            # only process inbound messages (messages you received), skip outbound
AZ_SINCE_ISO=                   # ISO-8601 timestamp to only sync messages after this datetime
SMS_OUTPUT_FILE=sms_messages.txt # text file to export all messages in readable format
SMS_JSON_OUTPUT_FILE=sms_messages.json # JSON file for machine-readable export
DRY_RUN=false                   # set to true to preview without creating Todoist tasks
DEBUG=false                     # set to true to print redacted request/response info
```

> **Note:** The script maintains an idempotency cache in `.sms_to_todoist_cache.json` so the same message is not turned into a task twice. You can delete the file if you ever need to resync everything from scratch.

## Running the sync

Once the environment variables are in place you can run the script directly:

```bash
python sms_to_todoist.py
```

For a dry run that shows which tasks would be created without contacting Todoist:

```bash
DRY_RUN=true python sms_to_todoist.py
```

To enable verbose debugging (request/response previews with sensitive data redacted):

```bash
DEBUG=true python sms_to_todoist.py
```

When you are satisfied with the automation you can schedule the command (for example with cron or a task runner) to keep Todoist in sync automatically.

## Export Formats

The script automatically exports all fetched SMS messages in two formats:

### Text File (`sms_messages.txt`)
Human-readable format with:
- Message date and timestamp
- Sender name
- Contact/lead name
- Full message content
- Message ID for reference

### JSON File (`sms_messages.json`)
Machine-readable format for integration with other tools:
```json
{
  "messages": [
    {
      "messageId": 123,
      "direction": "Inbound",
      "from": "customer@example.com",
      "to": "agent@example.com",
      "messageBody": "Hi, can you help me with my policy?",
      "timestamp": "2024-10-10T12:34:00Z"
    }
  ]
}
```

Both files are overwritten on each run with the latest messages. When using GitHub Actions, these files are automatically committed to the repository so you can easily access them.

## GitHub Actions Automation

This repository includes a GitHub Actions workflow (`.github/workflows/sms-to-todoist.yml`) that runs automatically every 30 minutes. To use it:

1. Go to your repository Settings → Secrets and variables → Actions
2. Add the following secrets:
   - `AGENCY_ZOOM_USERNAME` (required)
   - `AGENCY_ZOOM_PASSWORD` (required)
   - `TODOIST_API_TOKEN` (required)
   - `TODOIST_PROJECT_ID` (optional)
   - Other optional configuration variables as needed

The workflow will automatically commit the updated cache file back to the repository.

## Troubleshooting

- If you see `AgencyZoom unauthorized; check username/password`, double-check the credentials in the environment or `.env` file.
- Network issues are surfaced with `[error]` messages that include a short snippet of the upstream response to help with debugging.
- Increase `REQUEST_TIMEOUT_SECONDS` in the environment if AgencyZoom or Todoist is slow to respond from your network.

## Other utilities

The repository also contains legacy scripts retained for reference:

- `sync_agency_zoom_todoist.py`
- `az_sms_todoist_teams.py`
- `az_sms_todoist_teams_flat.py`
- `debug_api_structure.py`
- `updated export_contacts.py`

They are not actively maintained but remain available if you still rely on them.
