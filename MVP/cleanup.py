from __future__ import annotations
"""
Bidirectional Email Interface — MVP
Mailbox cleanup — delete sent emails after protocol obligations are fulfilled.

This module handles deletion of outbound DATA emails from the shared
mailbox once the sender has received all expected confirmations (ACK,
ATTACH_ACK) or the message has reached a terminal state (NACKED, FAILED).

It also provides lifetime-based expiry for orphaned emails that never
received any response.
"""

import imaplib
import email as email_lib
import logging
from datetime import datetime, timezone, timedelta

from envelope import (
    SUBJECT_PREFIX,
    HEADER_SENDER_ID,
    is_protocol_subject,
)
from state_store import (
    StateStore,
    OUT_ACKNOWLEDGED,
    OUT_NACKED,
    OUT_FAILED,
)

logger = logging.getLogger("app")
comm_log = logging.getLogger("comm")

# Terminal outbound states eligible for cleanup
_TERMINAL_STATES = {OUT_ACKNOWLEDGED, OUT_NACKED, OUT_FAILED}


def delete_sent_email(
    config: dict,
    message_id: str,
    sender_id: str,
    recipient_id: str,
) -> bool:
    """Delete a specific sent DATA email from the shared mailbox.

    Searches for an email whose subject contains the message_id and
    whose X-BEIS-Sender header matches *sender_id*.  The email is
    marked ``\\Deleted`` and the mailbox is expunged.

    Gmail puts self-to-self emails in Sent Mail (not INBOX), so we
    search multiple folders: INBOX first, then ``[Gmail]/All Mail``
    as a fallback.

    Returns True if the email was deleted or is already gone.
    This is best-effort — connection failures are logged but never raise.
    """
    # Build a search-friendly subject fragment:
    #   [BEIS] <sender> -> <recipient> DATA <message_id>
    subject_fragment = f"{sender_id} -> {recipient_id} DATA {message_id}"

    # Folders to search — INBOX first (cheapest), then All Mail (catches Sent)
    folders_to_search = ["INBOX", '"[Gmail]/All Mail"']

    # Gmail ignores \Deleted + EXPUNGE on [Gmail]/All Mail.
    # The correct approach is COPY to [Gmail]/Trash, then EXPUNGE from Trash.
    trash_folder = '"[Gmail]/Trash"'

    try:
        with imaplib.IMAP4_SSL(config["imap_host"], config["imap_port"]) as mailbox:
            mailbox.login(config["email_address"], config["email_password"])

            for folder in folders_to_search:
                try:
                    status, _ = mailbox.select(folder)
                    if status != "OK":
                        continue
                except imaplib.IMAP4.error:
                    continue

                search_query = f'(SUBJECT "{subject_fragment}")'
                status, msg_nums = mailbox.search(None, search_query)
                if status != "OK" or not msg_nums[0]:
                    continue

                trashed = False
                for num in msg_nums[0].split():
                    # Verify X-BEIS-Sender to avoid deleting another endpoint's mail
                    status, msg_data = mailbox.fetch(num, "(RFC822)")
                    if status != "OK":
                        continue

                    parsed = email_lib.message_from_bytes(msg_data[0][1])
                    hdr_sender = (parsed.get(HEADER_SENDER_ID) or "").strip()

                    if hdr_sender != sender_id:
                        logger.debug(
                            "Cleanup: skipping email #%s in %s — sender header '%s' != '%s'",
                            num, folder, hdr_sender, sender_id,
                        )
                        continue

                    # Move to Trash (Gmail-compatible deletion)
                    mailbox.copy(num, trash_folder)
                    mailbox.store(num, "+FLAGS", "\\Deleted")
                    trashed = True
                    logger.info(
                        "Cleanup: moved email to Trash from %s — msg_id=%s sender=%s",
                        folder, message_id, sender_id,
                    )

                if trashed:
                    mailbox.expunge()

                    # Permanently delete from Trash
                    try:
                        mailbox.select(trash_folder)
                        ts, tnums = mailbox.search(
                            None, f'(SUBJECT "{subject_fragment}")'
                        )
                        if ts == "OK" and tnums[0]:
                            for tnum in tnums[0].split():
                                mailbox.store(tnum, "+FLAGS", "\\Deleted")
                            mailbox.expunge()
                            logger.debug(
                                "Cleanup: permanently deleted from Trash — msg_id=%s",
                                message_id,
                            )
                    except Exception:
                        pass  # Trash cleanup is best-effort

                    comm_log.info(
                        "DELETE  DATA  msg_id=%s  sender=%s  recipient=%s  folder=%s",
                        message_id, sender_id, recipient_id, folder,
                    )
                    return True

            # Searched all folders, not found — email is already gone
            logger.info(
                "Cleanup: no email found for message %s in any folder (already deleted by receiver)",
                message_id,
            )
            return True
    except Exception as e:
        logger.warning("Cleanup failed for message %s: %s", message_id, e)
        return False


def _is_cleanup_eligible(record: dict) -> bool:
    """Check if an outbound record is eligible for email deletion.

    For text-only messages: terminal state is sufficient.
    For attachment messages: must also have received ATTACH_ACK.
    """
    state = record["state"]
    if state not in _TERMINAL_STATES:
        return False

    # Already cleaned
    if record.get("email_deleted"):
        return False

    # NACKED or FAILED — always eligible (no further confirmations expected)
    if state in (OUT_NACKED, OUT_FAILED):
        return True

    # ACKNOWLEDGED — check if attachment confirmation is needed
    envelope = record["envelope"]
    if envelope.get("has_attachment"):
        return record.get("attach_ack_received", False)

    # Text-only ACKNOWLEDGED — eligible
    return True


def cleanup_acknowledged(config: dict, state: StateStore) -> int:
    """Scan outbound messages in terminal states and delete their sent emails.

    Only deletes emails for messages that have fulfilled all protocol
    obligations (ACK for text-only, ACK + ATTACH_ACK for attachments,
    or NACKED / FAILED).

    Returns the count of emails successfully deleted.
    """
    my_id = config["endpoint_id"]
    deleted_count = 0

    for msg_id, record in list(state.data.get("outbound", {}).items()):
        if not _is_cleanup_eligible(record):
            continue

        envelope = record["envelope"]
        recipient_id = envelope["recipient_endpoint_id"]

        success = delete_sent_email(config, msg_id, my_id, recipient_id)
        state.mark_email_deleted(msg_id, success)
        if success:
            deleted_count += 1

    return deleted_count


def cleanup_expired(config: dict, state: StateStore) -> int:
    """Delete sent emails that have exceeded the configured maximum lifetime.

    Emails older than ``email_max_lifetime_days`` are deleted regardless
    of their acknowledgement state.  This catches orphaned emails where
    the receiver never responded.

    Messages not already in a terminal state are transitioned to FAILED.
    Skipped entirely if ``email_max_lifetime_days`` is 0.

    Returns the count of emails successfully deleted.
    """
    max_days = config.get("email_max_lifetime_days", 30)
    if max_days <= 0:
        return 0

    my_id = config["endpoint_id"]
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
    deleted_count = 0

    for msg_id, record in list(state.data.get("outbound", {}).items()):
        if record.get("email_deleted"):
            continue

        created_str = record.get("created_at", "")
        if not created_str:
            continue

        try:
            created = datetime.fromisoformat(created_str)
        except ValueError:
            logger.warning("Cleanup: invalid created_at for message %s", msg_id)
            continue

        if created >= cutoff:
            continue

        # Expired — delete the email
        envelope = record["envelope"]
        recipient_id = envelope["recipient_endpoint_id"]

        logger.info(
            "Cleanup: message %s expired (created %s, max lifetime %d days)",
            msg_id, created_str, max_days,
        )
        comm_log.info(
            "EXPIRE  DATA  msg_id=%s  age_days=%d  max=%d",
            msg_id,
            (datetime.now(timezone.utc) - created).days,
            max_days,
        )

        # Transition to FAILED if not already terminal
        if record["state"] not in _TERMINAL_STATES:
            state.update_outbound_state(msg_id, OUT_FAILED)

        success = delete_sent_email(config, msg_id, my_id, recipient_id)
        state.mark_email_deleted(msg_id, success)
        if success:
            deleted_count += 1

    return deleted_count
