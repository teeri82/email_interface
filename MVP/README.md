# Bidirectional Email Interface — MVP

A command-line application that sends and receives structured messages (with optional file attachments) between endpoints using a shared email account as the transport layer.

## Shared-Mailbox Architecture

**All endpoints use the same email account.** Endpoint identity is carried inside each message, not by email address:

| Identification layer | Where |
|---|---|
| `endpoint_id` | `config.json` — unique string per instance |
| `X-BEIS-Sender` / `X-BEIS-Recipient` | Custom email headers on every outgoing message |
| `sender_endpoint_id` / `recipient_endpoint_id` | JSON message body |
| Subject line | `[BEIS] <sender> -> <recipient> <type> <msg_id>` |

When polling, each endpoint only picks up messages where its own `endpoint_id` appears as the recipient. Messages for other endpoints are left untouched.

## Requirements

- Python 3.9+
- No external dependencies (standard library only)

## Quick Start

### 1. Configure

Copy the example config and fill in your credentials:

```bash
cp config.example.json config.json
# Edit config.json with your shared email credentials
```

```json
{
    "endpoint_id": "my-endpoint",
    "email_address": "shared-email@gmail.com",
    "email_password": "your-app-password",
    "smtp_host": "smtp.gmail.com",
    "smtp_port": 587,
    "imap_host": "imap.gmail.com",
    "imap_port": 993,
    "peers": [
        "peer-1",
        "peer-2"
    ],
    "polling_interval_seconds": 10,
    "ack_timeout_seconds": 60,
    "retry_count": 3,
    "retry_interval_seconds": 30,
    "protocol_version": "1.0",
    "email_max_lifetime_days": 30
}
```

| Field | Description |
|---|---|
| `endpoint_id` | Unique identifier for this endpoint instance |
| `email_address` / `email_password` | Shared email account credentials (same for all endpoints) |
| `peers` | List of peer endpoint IDs this endpoint communicates with |
| `polling_interval_seconds` | How often to check for new messages |
| `ack_timeout_seconds` | How long to wait for an ACK before retrying |
| `retry_count` | Maximum number of send retries |
| `email_max_lifetime_days` | Auto-delete sent emails older than this (0 = disabled, default 30) |

> **Gmail users:** Use an [App Password](https://support.google.com/accounts/answer/185833) — not your regular password. Enable IMAP in Gmail settings.

### 2. Run

```bash
cd /path/to/your/instance/directory
python3 /path/to/MVP/main.py
```

With a custom config path:

```bash
python3 /path/to/MVP/main.py -c /path/to/my-config.json
```

### 3. Send a message

```
> send peer-1 Hello, this is a test message!
Message sent (id: a1b2c3d4-...). Waiting for ACK…
```

With a file attachment (file must be in `out/`):

```
> send peer-1 Here is the report -f report.pdf
Message + attachment sent (id: a1b2c3d4-...). Waiting for ACK…
```

### 4. Receive messages

Inbound text messages are auto-saved to `in/<msg_id>/message.txt` on arrival:

```
[MESSAGE] From peer-1: Hello back!
```

Messages with attachments require a manual download step:

```
[MESSAGE+FILE] From peer-1: Here is the report
  📎 Attachment: report.pdf  (use 'dl a1b2c3d4' to download)
```

Use `dlpend` to list pending downloads and `dl <id-prefix>` to save:

```
> dlpend
--- Pending Attachment Downloads (1) ---
  a1b2c3d4…  from=peer-1  📎 report.pdf  payload=Here is the report

> dl a1b2c3d4
✅ Saved to in/a1b2c3d4-.../
   message.txt  (18 chars)
   report.pdf  (4096 bytes)
```

ACK / NACK / ATTACH_ACK notifications appear inline:

```
[ACK] Message a1b2c3d4-... acknowledged by peer-1
[ATTACH_ACK] Attachment for message a1b2c3d4… downloaded by peer-1
```

## CLI Commands

| Command | Description |
|---|---|
| `send <peer> <payload>` | Send a text-only DATA message |
| `send <peer> <payload> -f <file>` | Send a DATA message with a file attachment from `out/` |
| `status` | Show outbound / inbound message summary (📎 indicators for attachments) |
| `dlpend` | List messages with pending attachment downloads |
| `dl <msg_id_prefix>` | Download a pending attachment into `in/<msg_id>/` (tab-completable) |
| `peers` | List configured peer endpoint IDs |
| `info` | Show this endpoint's configuration |
| `help` / `help <cmd>` | Show available commands or help for a specific command |
| `quit` / `exit` / `Ctrl+D` | Shut down gracefully |

## Attachment Workflow

### Sending

1. Place the file in the `out/` subdirectory of your instance.
2. Run `send <peer> <payload> -f <filename>`.
3. You will receive an **ACK** (message received) and later an **ATTACH_ACK** (attachment downloaded by the receiver).

### Receiving

1. When a message with an attachment arrives, an **ACK** is sent immediately (confirming message receipt).
2. The attachment is **not** saved automatically — it is held in state as `ATTACH_PENDING`.
3. Use `dlpend` to see pending downloads.
4. Use `dl <msg_id_prefix>` to save both payload and attachment to `in/<msg_id>/`.
5. On download, an **ATTACH_ACK** is sent back to the sender.

### Directory Layout

```
your-instance/
├── config.json           # Endpoint configuration (you edit this)
├── state.json            # Auto-created — persistent message state
├── app.log               # Auto-created — application log
├── communication.log     # Auto-created — message traffic log
├── out/                  # Auto-created — place outbound attachments here
│   └── report.pdf
└── in/                   # Auto-created — received messages saved here
    └── <message-id>/
        ├── message.txt   # Payload text + metadata
        └── report.pdf    # Attachment file (if any)
```

## Running Multiple Instances

All instances share the **same email account** but use different `endpoint_id` values. Each runs from its own working directory:

```bash
# Terminal 1
cd instance-a && python3 /path/to/MVP/main.py

# Terminal 2
cd instance-b && python3 /path/to/MVP/main.py
```

Each instance gets its own `state.json`, logs, `in/`, and `out/` directories.

## Protocol Flow

### Text-only message

1. **Sender** builds a `DATA` envelope (with sender/recipient IDs) and sends via SMTP to the shared mailbox.
2. **Receiver** polls IMAP, filters by `[BEIS]` subject prefix and `X-BEIS-Recipient` header.
3. **Receiver** validates the JSON body, checks for duplicates, auto-saves payload to `in/<msg_id>/message.txt`, and sends **ACK** (or **NACK**).
4. **Sender** receives ACK → message marked `ACKNOWLEDGED`.
5. If no ACK within `ack_timeout_seconds`, sender retries up to `retry_count` times.
6. After all retries exhausted → message marked `FAILED`.

### Message with attachment

1. **Sender** builds a `DATA` envelope with `has_attachment: true`, attaches the file as a MIME part, and sends.
2. **Receiver** receives the message and sends **ACK** immediately. Attachment bytes are stored in state as `ATTACH_PENDING`.
3. **Receiver operator** runs `dl <id>` → payload + attachment saved to `in/<msg_id>/`, **ATTACH_ACK** sent to sender.
4. **Sender** receives `ATTACH_ACK` confirming the attachment was downloaded.

### Email Cleanup (automatic)

Sent DATA emails are automatically deleted from the shared mailbox once protocol obligations are fulfilled:

- **Text-only messages** → deleted after ACK (or NACK)
- **Attachment messages** → deleted after ACK **and** ATTACH_ACK (both required)
- **Failed messages** → deleted after retries exhausted
- **Orphaned messages** → deleted after `email_max_lifetime_days` (even without any response)

Cleanup happens in two places:
1. **Immediately** when a terminal state is reached (ACK, NACK, ATTACH_ACK, FAILED)
2. **Periodically** via a background sweep every 6 poll cycles (catches missed deletions + expiry)

> **Gmail note:** Self-to-self emails only appear in `[Gmail]/All Mail` (not INBOX). The cleanup module uses Gmail-compatible deletion (COPY to `[Gmail]/Trash` + EXPUNGE).

### Message Types

| Type | Direction | Description |
|---|---|---|
| `DATA` | Sender → Receiver | Carries application payload (optionally with a file attachment) |
| `ACK` | Receiver → Sender | Confirms receipt and acceptance of a DATA message |
| `NACK` | Receiver → Sender | Rejects a DATA message (with reason) |
| `ATTACH_ACK` | Receiver → Sender | Confirms the receiver downloaded the file attachment |

## Log Files

| File | Contents |
|---|---|
| `app.log` | Startup, config loading, errors, state transitions, retry scheduling |
| `communication.log` | Message traffic: every `SEND`, `RECV`, `RETRY`, `FAIL`, and `DL` event with IDs and payloads |

## Source Files

| File | Purpose |
|---|---|
| `main.py` | CLI application, background poller, retry scheduler |
| `envelope.py` | Message model, serialization, subject/header helpers |
| `transport.py` | SMTP send (with MIME attachments) and IMAP fetch (with attachment extraction) |
| `state_store.py` | JSON-backed persistent state tracking |
| `cleanup.py` | Mailbox cleanup — delete sent emails after protocol completion or expiry |
| `config_loader.py` | Load and validate `config.json` |
| `config.example.json` | Example configuration (safe to commit — no credentials) |
| `regression_tests.py` | Regression test suite — 40 unit + 5 live tests |

## Known Limitations (MVP)

- **No encryption** — messages and attachments travel as plain-text email. Use only on trusted accounts.
- **No concurrent access** — `state.json` is not locked; running two instances from the same directory will corrupt state.
- **Polling-based** — no push/IDLE support; latency depends on `polling_interval_seconds`.
- **Attachment size** — limited by email provider caps and the hex-encoding overhead in `state.json`.
- **Retry does not re-attach files** — retries resend the envelope JSON only (the original attachment is not re-sent).

## Testing

Run the regression test suite (unit tests — no credentials needed):

```bash
cd MVP && python3 regression_tests.py
```

Run with live IMAP/SMTP tests (requires `config.json` with valid credentials):

```bash
cd your-instance-dir && python3 /path/to/MVP/regression_tests.py --live
```

The suite covers config loading, envelope serialization, state store operations, import chain integrity, cleanup eligibility logic, and live send/fetch/delete round-trips.

## Security Note

`config.json` contains email credentials in plain text. **Do not commit it to version control.** Add it (along with generated artifacts) to `.gitignore`:

```
config.json
state.json
*.log
in/
out/
```
