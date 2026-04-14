# Bidirectional Email Interface System (BEIS)

A reliable, bidirectional communication system that uses a **shared email account** as the transport layer. Multiple endpoints exchange structured messages (with optional file attachments) over SMTP/IMAP — no dedicated server infrastructure required.

## How It Works

All endpoints share one email account. Identity is carried inside each message via custom headers and JSON fields, not by email address:

```
Endpoint A  ──SMTP──▶  Shared Mailbox  ◀──IMAP──  Endpoint B
   (sender)                                         (receiver)
```

Each endpoint polls the shared mailbox and picks up only messages addressed to it. A built-in ACK/NACK protocol ensures delivery confirmation, and automatic retries handle transient failures.

### Message Types

| Type | Direction | Purpose |
|------|-----------|---------|
| `DATA` | Sender → Receiver | Carries payload text and optional file attachment |
| `ACK` | Receiver → Sender | Confirms receipt of a DATA message |
| `NACK` | Receiver → Sender | Rejects a DATA message (with reason) |
| `ATTACH_ACK` | Receiver → Sender | Confirms the receiver downloaded the file attachment |

## Repository Structure

```
├── README.md                                    # This file
├── Bidirectional Email Interface Specificat.md   # Full protocol specification
├── .gitignore
└── MVP/                                         # MVP implementation (current)
    ├── README.md              # Detailed MVP usage guide
    ├── MVP_devlog.md          # Development log with test results and bug fixes
    ├── mvp_instructions.md    # Original build instructions
    ├── mvp_devlog_instructions.md  # Devlog generation instructions
    ├── main.py                # CLI application, background poller, retry scheduler
    ├── envelope.py            # Message model, JSON serialization, subject/header helpers
    ├── transport.py           # SMTP send and IMAP fetch with MIME attachment support
    ├── state_store.py         # JSON-backed persistent state tracking
    ├── config_loader.py       # Configuration file loader and validator
    └── config.example.json    # Example configuration (safe to commit)
```

## Current Development Status

### ✅ MVP — Complete and Tested

The MVP is a **Python 3.9+ CLI application** with zero external dependencies. It lives in `MVP/` and implements the core protocol from the specification.

**What works:**

- Shared-mailbox architecture — all endpoints use the same email account
- Send and receive text messages with delivery confirmation (ACK)
- Send and receive file attachments with deferred download and ATTACH_ACK
- Automatic retry with configurable timeout and retry count
- IMAP polling at configurable intervals
- Duplicate detection by message ID
- Persistent state tracking via JSON file
- Dual logging — `app.log` (application events) and `communication.log` (message traffic)
- Multiple instances running from separate directories
- Endpoint routing via `X-BEIS-*` custom email headers and structured subject lines
- Input validation (unknown peers, missing payloads, missing attachment files)

**Tested scenarios** (all passing — see `MVP/MVP_devlog.md` for full evidence):

- CLI commands: `send`, `status`, `peers`, `info`, `dlpend`, `dl`, `help`, `quit`
- Plain text message send + receive + auto-ACK
- File attachment send + deferred download + ATTACH_ACK
- SMTP failure handling (message state → FAILED)
- Peer validation, payload validation, missing file validation
- Duplicate ACK handling across polling sessions

### 🔲 Not Yet Implemented (from Specification)

| Feature | Spec Reference |
|---------|---------------|
| Encryption (AES-256 shared symmetric key) | FR-88 – FR-96 |
| Key generation utility | FR-96b – FR-96h |
| Key rotation | FR-96a |
| Heartbeat / health monitoring | FR-102 – FR-110 |
| Protocol version negotiation | FR-24 – FR-27 |
| NACK sending by receiver | — |
| Integrity hash (SHA-256) in envelope | FR-19 |
| Machine-readable error classification | FR-116 – FR-121 |
| Configurable log levels | — |

### ⚠️ Known Limitations

- **No encryption** — messages travel as plaintext email
- **No message deletion** — processed emails accumulate in the shared mailbox
- **No concurrent access** — `state.json` has no file locking
- **Polling-based only** — no IMAP IDLE/push support
- **Single attachment per message** — multiple attachments not supported
- **Attachment data stored in state** — large files inflate `state.json` via base64 encoding
- **Retry does not re-attach files** — retries resend the JSON envelope only

## Quick Start

```bash
cd MVP
cp config.example.json config.json
# Edit config.json with your shared email credentials and endpoint ID
python3 main.py
```

> **Gmail users:** Use an [App Password](https://support.google.com/accounts/answer/185833), not your regular password. Enable IMAP in Gmail settings.

See [`MVP/README.md`](MVP/README.md) for the full usage guide, CLI command reference, and protocol details.

## Requirements

- Python 3.9+
- No external dependencies (standard library only)

## Documentation

| Document | Description |
|----------|-------------|
| [`MVP/README.md`](MVP/README.md) | Full usage guide with CLI reference, protocol flow, and directory layout |
| [`MVP/MVP_devlog.md`](MVP/MVP_devlog.md) | Development log — chronological build log, test results, bugs and fixes |
| [`Bidirectional Email Interface Specificat.md`](Bidirectional%20Email%20Interface%20Specificat.md) | Complete protocol specification with all functional requirements |
