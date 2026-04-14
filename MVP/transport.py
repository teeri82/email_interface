from __future__ import annotations
"""
Bidirectional Email Interface — MVP
Email transport — send and receive via SMTP/IMAP.

All endpoints share the SAME email account.  Endpoint identity is
conveyed through custom email headers (X-BEIS-Sender, X-BEIS-Recipient)
and inside the JSON envelope body.  The IMAP poller filters messages
by recipient header so each endpoint only processes mail addressed to it.
"""

import smtplib
import imaplib
import email as email_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import logging
import os

from envelope import (
    build_email_subject,
    serialize_envelope,
    deserialize_envelope,
    is_protocol_subject,
    SUBJECT_PREFIX,
    HEADER_SENDER_ID,
    HEADER_RECIPIENT_ID,
)

logger = logging.getLogger("app")


def send_email(config: dict, envelope: dict, attachment_path: str | None = None) -> bool:
    """Send a protocol message as an email to the shared mailbox.

    Because all endpoints use the same email account, the email is sent
    from and to the same address.  The sender / recipient endpoint IDs
    are carried in custom X-BEIS-* headers and in the JSON body so the
    receiving endpoint can identify messages intended for it.

    If *attachment_path* is provided the file is added as a MIME attachment.

    Returns True on success.
    """
    shared_email = config["email_address"]

    subject = build_email_subject(
        envelope["message_type"],
        envelope["message_id"],
        envelope["sender_endpoint_id"],
        envelope["recipient_endpoint_id"],
    )
    body = serialize_envelope(envelope)

    if attachment_path:
        # Build multipart message with JSON body + file attachment
        msg = MIMEMultipart()
        msg.attach(MIMEText(body, "plain", "utf-8"))

        filename = os.path.basename(attachment_path)
        with open(attachment_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)
    else:
        msg = MIMEText(body, "plain", "utf-8")

    msg["From"] = shared_email
    msg["To"] = shared_email          # same mailbox
    msg["Subject"] = subject
    msg[HEADER_SENDER_ID] = envelope["sender_endpoint_id"]
    msg[HEADER_RECIPIENT_ID] = envelope["recipient_endpoint_id"]

    try:
        with smtplib.SMTP(config["smtp_host"], config["smtp_port"], timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(shared_email, config["email_password"])
            server.sendmail(shared_email, [shared_email], msg.as_string())
        logger.info(
            "Email sent: %s → %s [%s %s]%s (via %s)",
            envelope["sender_endpoint_id"],
            envelope["recipient_endpoint_id"],
            envelope["message_type"],
            envelope["message_id"],
            f" +attachment:{os.path.basename(attachment_path)}" if attachment_path else "",
            shared_email,
        )
        return True
    except Exception as e:
        logger.error(
            "Failed to send email (%s → %s): %s",
            envelope["sender_endpoint_id"],
            envelope["recipient_endpoint_id"],
            e,
        )
        return False


def fetch_protocol_emails(config: dict) -> list[dict]:
    """Poll the shared IMAP mailbox and return envelopes addressed to this endpoint.

    Only messages whose X-BEIS-Recipient header (or JSON recipient_endpoint_id)
    matches our endpoint_id are returned.  Messages we sent ourselves (our
    endpoint_id appears as X-BEIS-Sender) are left in the mailbox for the
    intended recipient to pick up — unless we are also the recipient (loopback).

    If an email carries a file attachment, the envelope dict will contain:
        _attachment_data: bytes   — raw file content
        _attachment_filename: str — original filename

    Processed messages are marked as read.  For ACK/NACK/ATTACH_ACK
    emails (responses), the receiver moves them to Trash so they don't
    accumulate.  Sent DATA emails are left for cleanup.py to handle
    after the full protocol round-trip completes.

    Gmail self-to-self emails only appear in ``[Gmail]/All Mail``
    (not INBOX), so we search both folders.
    """
    my_id = config["endpoint_id"]
    envelopes: list[dict] = []
    delete_nums: list[bytes] = []
    active_folder: str = "INBOX"

    try:
        with imaplib.IMAP4_SSL(config["imap_host"], config["imap_port"]) as mailbox:
            mailbox.login(config["email_address"], config["email_password"])

            # Try INBOX first; fall back to [Gmail]/All Mail for self-to-self setups
            found_messages = False
            for folder in ["INBOX", '"[Gmail]/All Mail"']:
                try:
                    status, _ = mailbox.select(folder)
                    if status != "OK":
                        continue
                except imaplib.IMAP4.error:
                    continue
                active_folder = folder
                probe_status, probe_nums = mailbox.search(
                    None, f'(SUBJECT "{SUBJECT_PREFIX}")'
                )
                if probe_status == "OK" and probe_nums[0]:
                    found_messages = True
                    break

            if not found_messages:
                return envelopes

            # We already searched in the selected folder — use the results
            msg_nums = probe_nums

            for num in msg_nums[0].split():
                try:
                    status, msg_data = mailbox.fetch(num, "(RFC822)")
                    if status != "OK":
                        continue

                    raw_email = msg_data[0][1]
                    parsed = email_lib.message_from_bytes(raw_email)
                    subject = parsed.get("Subject", "")

                    if not is_protocol_subject(subject):
                        continue

                    # --- Endpoint filtering via custom headers ---
                    hdr_recipient = (parsed.get(HEADER_RECIPIENT_ID) or "").strip()
                    hdr_sender = (parsed.get(HEADER_SENDER_ID) or "").strip()

                    # Skip messages not addressed to us
                    if hdr_recipient and hdr_recipient != my_id:
                        continue

                    # Skip messages we sent ourselves (unless loopback)
                    if hdr_sender == my_id and hdr_recipient != my_id:
                        continue

                    # Extract body text and any file attachment
                    body = ""
                    attachment_data: bytes | None = None
                    attachment_filename: str | None = None

                    if parsed.is_multipart():
                        for part in parsed.walk():
                            content_type = part.get_content_type()
                            disposition = str(part.get("Content-Disposition") or "")

                            if "attachment" in disposition:
                                # File attachment part
                                attachment_data = part.get_payload(decode=True)
                                attachment_filename = part.get_filename() or "unnamed_attachment"
                            elif content_type == "text/plain" and not body:
                                charset = part.get_content_charset() or "utf-8"
                                body = part.get_payload(decode=True).decode(charset)
                    else:
                        charset = parsed.get_content_charset() or "utf-8"
                        body = parsed.get_payload(decode=True).decode(charset)

                    envelope = deserialize_envelope(body)
                    if not envelope:
                        logger.warning("Discarded malformed protocol email (subject: %s)", subject)
                        delete_nums.append(num)
                        continue

                    # Double-check JSON body matches headers (defence in depth)
                    json_recipient = envelope.get("recipient_endpoint_id", "")
                    if json_recipient != my_id:
                        # Header said it's ours but body disagrees — skip
                        logger.warning(
                            "Header/body mismatch: header recipient=%s, body recipient=%s — skipping",
                            hdr_recipient, json_recipient,
                        )
                        continue

                    # Attach raw file data to envelope dict for caller to handle
                    if attachment_data is not None:
                        envelope["_attachment_data"] = attachment_data
                        envelope["_attachment_filename"] = attachment_filename

                    envelopes.append(envelope)
                    delete_nums.append(num)
                    logger.info(
                        "Fetched protocol email: %s -> %s %s %s%s",
                        envelope["sender_endpoint_id"],
                        envelope["recipient_endpoint_id"],
                        envelope["message_type"],
                        envelope["message_id"],
                        f" +attachment:{attachment_filename}" if attachment_data else "",
                    )

                except Exception as e:
                    logger.error("Error processing email #%s: %s", num, e)

            # Delete consumed messages from the mailbox.
            # Gmail ignores \Deleted+EXPUNGE on [Gmail]/All Mail, so we
            # COPY to [Gmail]/Trash first (Gmail-compatible deletion).
            if delete_nums:
                trash_folder = '"[Gmail]/Trash"'
                for num in delete_nums:
                    try:
                        mailbox.copy(num, trash_folder)
                        mailbox.store(num, "+FLAGS", "\\Deleted")
                    except Exception as e:
                        logger.error("Failed to trash email #%s: %s", num, e)
                mailbox.expunge()

    except imaplib.IMAP4.error as e:
        logger.error("IMAP error: %s", e)
    except Exception as e:
        logger.error("Mailbox fetch failed: %s", e)

    return envelopes
