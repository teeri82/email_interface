# Email Deletion Feature — Specification

## 1. Problem Statement

### 1.1 Current Behaviour

The shared mailbox accumulates protocol emails indefinitely. Two categories of emails are affected:

| Email type | Current handling |
|---|---|
| **Inbound emails** (addressed to this endpoint) | Deleted by `transport.fetch_protocol_emails()` after extraction — ✅ already handled |
| **Outbound DATA emails** (sent by this endpoint) | **Never deleted** — remain in the shared mailbox forever ❌ |

### 1.2 Devlog Warning-Level Inconsistency

**Devlog Test 4.14** documented repeated "unknown outbound message" warnings when ACK emails were re-fetched across sessions. This was caused by an earlier version of `transport.py` that did not delete consumed emails. The current code **does** delete inbound emails after fetch (lines 218–222 of `transport.py`), so those warnings should no longer occur on a fresh run.

However, the **original sent DATA emails** still linger in the mailbox. When the receiver's poller re-encounters these (they're addressed to someone else), it skips them — but they waste IMAP search/fetch cycles on every poll. This feature fixes that.

### 1.3 Spec Reference

- **FR-52c**: "Only messages that have been fully processed (accepted or rejected) by the local endpoint shall be deleted from the shared mailbox."
- **Section 8 (line 590)**: "Only fully processed messages (accepted or rejected by this endpoint) are deleted from the shared mailbox."

## 2. Desired Behaviour

After the **sender** node has received confirmation that all protocol obligations are fulfilled for an outbound DATA message, it shall delete the original DATA email from the shared mailbox.

### 2.1 Deletion Trigger Conditions

| Message type | Delete when |
|---|---|
| **Text-only DATA** (no attachment) | ACK received → outbound state becomes `ACKNOWLEDGED` |
| **DATA with attachment** | ACK received **AND** ATTACH_ACK received → both confirmations fulfilled |
| **NACK'd DATA** | NACK received → outbound state becomes `NACKED` (message rejected, safe to remove) |
| **FAILED DATA** | All retries exhausted → outbound state becomes `FAILED` (giving up, clean up) |
| **Expired DATA** | Email age exceeds `email_max_lifetime_days` — deleted regardless of state (catch-all for orphaned emails that never received any response) |

### 2.2 Identification of the Sent Email

The sender must identify its own original DATA email in the shared mailbox. This is done by searching for:

- Subject matching `[BEIS] <sender_id> -> <recipient_id> DATA <message_id>`
- `X-BEIS-Sender` header matching this endpoint's `endpoint_id`

The `message_id` from the envelope uniquely identifies the email to delete.

### 2.3 Safety Rules

1. **Never delete emails addressed to other endpoints** — filter by `X-BEIS-Sender` matching self.
2. **Never delete emails that are not yet in a terminal state** — only delete when state is `ACKNOWLEDGED`, `NACKED`, or `FAILED`.
3. **Best-effort deletion** — if the IMAP delete fails (connection error, email already gone), log a warning but do NOT fail the state transition. Deletion is a cleanup optimisation, not a protocol requirement.
4. **Attachment messages require both confirmations** — do not delete a DATA+attachment email after only the ACK; wait for ATTACH_ACK too.
5. **Lifetime-based expiry** — if an email has been in the mailbox longer than `email_max_lifetime_days` (configurable, default 30), it is deleted unconditionally. This prevents orphaned emails from accumulating when an ACK is never received (e.g. the receiver endpoint is permanently offline).

### 2.4 Configuration

Add to `config.json`:

```json
"email_max_lifetime_days": 30
```

| Field | Type | Default | Description |
|---|---|---|---|
| `email_max_lifetime_days` | int | 30 | Maximum age in days for a sent DATA email in the mailbox. Emails older than this are deleted regardless of acknowledgement state. Set to `0` to disable lifetime-based expiry. |

## 3. Module Design

### 3.1 New Module: `cleanup.py`

A separate module responsible for mailbox cleanup operations.

**Functions:**

```
delete_sent_email(config, message_id, sender_id, recipient_id) -> bool
```

- Connects to IMAP
- Searches for `[BEIS] <sender_id> -> <recipient_id> DATA <message_id>` in subject
- Verifies `X-BEIS-Sender` matches `sender_id`
- Marks for deletion + expunges
- Returns True on success, False on failure
- Logs all operations to `app` logger

```
cleanup_acknowledged(config, state) -> int
```

- Scans outbound messages in terminal states (`ACKNOWLEDGED`, `NACKED`, `FAILED`)
- For `ACKNOWLEDGED` messages with attachments: only deletes if ATTACH_ACK has been received (tracked via a new state field)
- Calls `delete_sent_email()` for each eligible message
- Marks cleaned messages in state (new field `email_deleted: true`) to avoid re-attempting
- Returns count of emails deleted

```
cleanup_expired(config, state) -> int
```

- Scans all outbound messages where `email_deleted` is not true
- Compares `created_at` against current time minus `email_max_lifetime_days`
- Deletes any email older than the configured lifetime, regardless of state
- Marks `email_deleted: true` and transitions state to `FAILED` if not already terminal
- Skipped entirely if `email_max_lifetime_days` is `0`
- Returns count of emails deleted

### 3.2 State Store Changes

Add to outbound records:
- `email_deleted: bool` — tracks whether the sent email has been cleaned from the mailbox
- `attach_ack_received: bool` — tracks whether ATTACH_ACK has been received (for attachment messages)

### 3.3 Integration Points

| Where | Change |
|---|---|
| `main.py` → `_handle_inbound_ack()` | After setting `ACKNOWLEDGED`, set `attach_ack_received = True` if no attachment, then call cleanup |
| `main.py` → `_handle_inbound_attach_ack()` | Set `attach_ack_received = True`, then call cleanup |
| `main.py` → `_handle_inbound_nack()` | After setting `NACKED`, call cleanup |
| `main.py` → `retry_check()` | After setting `FAILED`, call cleanup |
| `main.py` → `BackgroundWorker.run()` | Optionally run `cleanup_acknowledged()` and `cleanup_expired()` periodically as a catch-all |

## 4. Test Plan

### Test 4.1 — Unit: delete_sent_email() with matching email

| Field | Value |
|---|---|
| **Setup** | Send a DATA message from test1 to test2. Verify email exists in mailbox via IMAP search. |
| **Action** | Call `delete_sent_email(config, msg_id, "endpoint-1", "endpoint-2")` |
| **Expected** | Returns True. Email no longer found in IMAP search. |

### Test 4.2 — Unit: delete_sent_email() with no matching email

| Field | Value |
|---|---|
| **Action** | Call `delete_sent_email(config, "nonexistent-id", "endpoint-1", "endpoint-2")` |
| **Expected** | Returns False. Warning logged. No crash. |

### Test 4.3 — Integration: Text-only message auto-deleted after ACK

| Field | Value |
|---|---|
| **Setup** | test1 sends a text-only DATA to test2. |
| **Action** | test2 polls and ACKs. test1 receives ACK. |
| **Expected** | test1 outbound state = `ACKNOWLEDGED`, `email_deleted = true`. Original DATA email no longer in shared mailbox. |

### Test 4.4 — Integration: Attachment message deleted only after ATTACH_ACK

| Field | Value |
|---|---|
| **Setup** | test1 sends DATA+attachment to test2. |
| **Action** | test2 ACKs. test1 receives ACK. |
| **Expected** | test1 state = `ACKNOWLEDGED`, `email_deleted = false` (waiting for ATTACH_ACK). |
| **Action** | test2 runs `dl`, ATTACH_ACK sent. test1 receives ATTACH_ACK. |
| **Expected** | `attach_ack_received = true`, `email_deleted = true`. Original DATA email deleted. |

### Test 4.5 — Integration: NACK'd message auto-deleted

| Field | Value |
|---|---|
| **Setup** | Simulate a NACK scenario (or manually inject). |
| **Expected** | After NACK, outbound state = `NACKED`, `email_deleted = true`. |

### Test 4.6 — Integration: FAILED message auto-deleted after retries exhausted

| Field | Value |
|---|---|
| **Setup** | Send with short timeout, no receiver running. |
| **Expected** | After retries exhausted, state = `FAILED`, `email_deleted = true`. |

### Test 4.7 — Safety: emails for other endpoints are not deleted

| Field | Value |
|---|---|
| **Setup** | test1 sends to test2. Before test2 polls, run cleanup from test1. |
| **Expected** | Only the DATA email *sent by test1* is deleted. Any emails sent by test2 remain untouched. |

### Test 4.8 — Idempotency: double cleanup does not crash

| Field | Value |
|---|---|
| **Action** | Run cleanup twice for the same message. |
| **Expected** | First call deletes. Second call finds nothing, returns False, logs info. No crash. |

### Test 4.9 — Resilience: IMAP connection failure during cleanup

| Field | Value |
|---|---|
| **Setup** | Misconfigure IMAP host temporarily. |
| **Action** | Trigger cleanup. |
| **Expected** | Returns False, error logged, state NOT corrupted, `email_deleted` stays false (will retry later). |

### Test 4.10 — Lifetime expiry: old email deleted even without ACK

| Field | Value |
|---|---|
| **Setup** | Send a DATA message from test1. Manually backdate `created_at` in `state.json` to exceed `email_max_lifetime_days`. |
| **Action** | Run `cleanup_expired()`. |
| **Expected** | Email deleted from mailbox. Outbound state → `FAILED`, `email_deleted = true`. |

### Test 4.11 — Lifetime expiry disabled when set to 0

| Field | Value |
|---|---|
| **Setup** | Set `email_max_lifetime_days: 0` in config. Backdate a message. |
| **Action** | Run `cleanup_expired()`. |
| **Expected** | No emails deleted. Returns 0. |

## 5. Development Process

- Develop `cleanup.py` as a separate module
- Integrate with `main.py` at the trigger points listed in Section 3.3
- Add state fields to `state_store.py`
- Run all tests from Section 4, record results
- Maintain `email_deletion_devlog.md` throughout development
- Update `MVP/README.md` with the new behaviour