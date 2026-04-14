# Email Deletion Feature — Development Log

---

## 1. Overview

**Feature:** Automatic deletion of sent DATA emails from the shared mailbox after protocol obligations are fulfilled.

**Branch:** `feature/email-deletion`

**Spec:** `emaildeletion_spec.md`

**New module:** `cleanup.py` — mailbox cleanup operations

---

## 2. Module Changes

| File | Changes |
|------|---------|
| `cleanup.py` | **Created** — `delete_sent_email()`, `cleanup_acknowledged()`, `cleanup_expired()` |
| `state_store.py` | Added `mark_email_deleted()`, `set_attach_ack_received()` methods |
| `main.py` | Added `_try_cleanup()` helper; updated ACK/NACK/ATTACH_ACK handlers + retry FAILED path + periodic background cleanup |
| `config_loader.py` | Added `email_max_lifetime_days: 30` default |
| `config.example.json` | Added `email_max_lifetime_days` field |
| `transport.py` | **BUG-004 fix** — multi-folder IMAP search + Gmail-compatible Trash deletion |

---

## 3. Build Log

### 3.1 — Created `cleanup.py`

New module with three functions:
- `delete_sent_email(config, message_id, sender_id, recipient_id)` — IMAP multi-folder search (INBOX then `[Gmail]/All Mail`) by subject fragment + `X-BEIS-Sender` header verification, COPY to `[Gmail]/Trash` + expunge (Gmail-compatible deletion). Best-effort, returns bool.
- `cleanup_acknowledged(config, state)` — scans terminal-state outbound messages, checks eligibility (text-only needs ACK; attachment needs ACK + ATTACH_ACK; NACKED/FAILED always eligible), calls `delete_sent_email()`, marks `email_deleted` in state.
- `cleanup_expired(config, state)` — scans outbound messages older than `email_max_lifetime_days`, transitions non-terminal to FAILED, deletes email. Disabled when config is 0.

### 3.2 — State store additions

- `mark_email_deleted(message_id, deleted)` — sets `email_deleted` bool + updates timestamp
- `set_attach_ack_received(message_id)` — sets `attach_ack_received = True` + updates timestamp

### 3.3 — main.py integration

- `_try_cleanup(config, state, message_id)` — best-effort wrapper that checks `email_deleted` flag before calling `delete_sent_email()`
- `_handle_inbound_ack()` — now accepts `config`; triggers cleanup for text-only messages after ACK
- `_handle_inbound_nack()` — now accepts `config`; triggers cleanup after NACK
- `_handle_inbound_attach_ack()` — now accepts `config`; calls `state.set_attach_ack_received()` then triggers cleanup
- `retry_check()` — triggers cleanup when message transitions to FAILED
- `BackgroundWorker.run()` — runs `cleanup_acknowledged()` + `cleanup_expired()` every 6th poll cycle
- `process_inbound()` — updated dispatcher to pass `config` to all handlers

### 3.4 — Compile check

All modules import cleanly on Python 3.9+. Both test instances verified.

### 3.5 — BUG-004: Gmail self-to-self emails not in INBOX (transport + cleanup)

**Discovery:** During testing, found that Gmail puts self-to-self emails (same From and To address) exclusively in Sent Mail / All Mail — they **never** appear in INBOX. This broke both:
1. `cleanup.py` — initial version only searched INBOX, never found sent DATA emails
2. `transport.py` `fetch_protocol_emails()` — only searched INBOX, could not find any self-to-self protocol emails

**Root cause:** Gmail IMAP treats self-to-self emails as "sent only" and does not deliver them to INBOX. All BEIS emails in the shared mailbox had only the `\Sent` Gmail label.

**Fix — cleanup.py:** Multi-folder search: INBOX first, then `[Gmail]/All Mail` as fallback. Also discovered that Gmail ignores `\Deleted` + EXPUNGE on `[Gmail]/All Mail`, so switched to COPY-to-`[Gmail]/Trash` + EXPUNGE (Gmail-compatible permanent deletion).

**Fix — transport.py:** Same multi-folder search pattern for `fetch_protocol_emails()`. Updated deletion of consumed messages to use the same COPY-to-Trash approach.

**Impact:** This was a **latent bug in the original MVP** — all previous tests only worked because Gmail sometimes delivered messages to INBOX during earlier sessions. The fix ensures reliable operation with Gmail's actual IMAP behavior.

---

## 4. Test Results

### Test 4.1 — Unit: delete_sent_email() with matching email

| Field | Value |
|---|---|
| **Status** | ✅ PASS |
| **Details** | Sent DATA email `c96dfaab` (test1 → test2, text-only). Called `delete_sent_email()` directly. Email found in `[Gmail]/All Mail` (not INBOX — confirming Gmail behavior), `X-BEIS-Sender` verified, moved to Trash via COPY, expunged. Returned `True`. Verified email gone from All Mail. |
| **Note** | First attempt used `\Deleted` + EXPUNGE which Gmail ignored on All Mail. Led to BUG-004 fix (COPY to Trash). |

### Test 4.2 — Unit: delete_sent_email() with no matching email

| Field | Value |
|---|---|
| **Status** | ✅ PASS |
| **Details** | Called with `nonexistent-id-12345`. Searched INBOX and All Mail, found nothing. Returned `True` (treated as "already gone"). No crash. |

### Test 4.3 — Integration: Text-only message auto-deleted after ACK

| Field | Value |
|---|---|
| **Status** | ✅ PASS |
| **Details** | Sent text-only DATA `96cb7fb6` from test1. Ran test2 `process_inbound()` — received DATA from `[Gmail]/All Mail` (transport.py fix working), sent ACK. Ran test1 `process_inbound()` — received ACK, transitioned to ACKNOWLEDGED, `_try_cleanup()` triggered, `email_deleted=True`. |
| **Note** | Also validated transport.py BUG-004 fix — test2 found DATA emails in All Mail that were previously invisible in INBOX. |

### Test 4.4 — Integration: Attachment message deleted only after ATTACH_ACK

| Field | Value |
|---|---|
| **Status** | ✅ PASS |
| **Details** | Sent attachment DATA `c22b1479` (with `test44.txt`). After ACK only: `email_deleted=False`, `attach_ack_received=False` — cleanup correctly skipped. After ATTACH_ACK: `attach_ack_received=True`, `email_deleted=True` — cleanup triggered. Two-phase deletion working. |

### Test 4.5 — Integration: NACK'd message auto-deleted

| Field | Value |
|---|---|
| **Status** | ✅ PASS |
| **Details** | Sent DATA `12579722`, manually sent NACK from test2. test1 received ACK first (Gmail delivery order), which triggered cleanup (text-only). NACK then transitioned to NACKED. Final: `state=NACKED`, `email_deleted=True`. Confirmed actual email deletion from `[Gmail]/All Mail` via COPY-to-Trash. |

### Test 4.6 — Integration: FAILED message auto-deleted after retries exhausted

| Field | Value |
|---|---|
| **Status** | ✅ PASS |
| **Details** | Created synthetic FAILED outbound record. `cleanup_acknowledged()` detected it as eligible (FAILED is terminal), attempted deletion (no email found = "already gone"), `email_deleted=True`. |

### Test 4.7 — Safety: emails for other endpoints are not deleted

| Field | Value |
|---|---|
| **Status** | ✅ PASS |
| **Details** | Sent DATA `13ec8b6c` from endpoint-1. Called `delete_sent_email()` with wrong `sender_id='endpoint-WRONG'`. Email found by subject but `X-BEIS-Sender` didn't match — skipped. Email still existed (verified by direct IMAP). Then deleted with correct sender — succeeded. |

### Test 4.8 — Idempotency: double cleanup does not crash

| Field | Value |
|---|---|
| **Status** | ✅ PASS |
| **Details** | Ran `cleanup_acknowledged()` twice on already-deleted messages. Both returned 0 (skipped `email_deleted=True`). Ran `cleanup_expired()` — returned 0. No crash, no errors. |

### Test 4.9 — Resilience: IMAP connection failure during cleanup

| Field | Value |
|---|---|
| **Status** | ✅ PASS |
| **Details** | Called `delete_sent_email()` with bad IMAP credentials. Exception caught, logged `"Cleanup failed: [AUTHENTICATIONFAILED]"`, returned `False`. No crash. |

### Test 4.10 — Lifetime expiry: old email deleted even without ACK

| Field | Value |
|---|---|
| **Status** | ✅ PASS |
| **Details** | Synthetic outbound in `WAITING_FOR_ACK` with `created_at` 2 days ago. `email_max_lifetime_days=1`. `cleanup_expired()` detected as expired, transitioned to FAILED, `email_deleted=True`. |

### Test 4.11 — Lifetime expiry disabled when set to 0

| Field | Value |
|---|---|
| **Status** | ✅ PASS |
| **Details** | Synthetic outbound 100 days old. `email_max_lifetime_days=0`. `cleanup_expired()` returned 0 — message untouched, `state=WAITING_FOR_ACK`, `email_deleted=False`. |

---

## 5. Failures and Fixes

### BUG-004: Gmail self-to-self IMAP routing

- **Symptom:** `delete_sent_email()` found nothing in INBOX; `fetch_protocol_emails()` found nothing in INBOX
- **Cause:** Gmail does not deliver self-to-self emails to INBOX; they only have `\Sent` label
- **Fix:** Multi-folder search (INBOX → `[Gmail]/All Mail`) in both `cleanup.py` and `transport.py`
- **Additional fix:** Gmail ignores `\Deleted` + EXPUNGE on All Mail; switched to COPY-to-`[Gmail]/Trash` approach
- **Files changed:** `cleanup.py`, `transport.py`
- **Impact:** Latent bug in original MVP transport layer; all BEIS email retrieval was unreliable with Gmail

---

## 6. Final State

All 11 tests passing. Email deletion feature is complete and working.

**Summary of changes:**
- `cleanup.py` — new module, Gmail-aware multi-folder deletion
- `state_store.py` — 2 new tracking methods
- `main.py` — cleanup integrated into all terminal-state transitions + periodic background sweep
- `config_loader.py` + `config.example.json` — `email_max_lifetime_days` config
- `transport.py` — BUG-004 fix: multi-folder search + Gmail-compatible deletion

**Key discovery:** Gmail IMAP self-to-self email routing required fundamental changes to both the cleanup module and the core transport layer.
