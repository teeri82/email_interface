from __future__ import annotations
"""
Bidirectional Email Interface — MVP
Envelope and message model.

All endpoints share the same email account.  Endpoint identity is
carried inside the protocol message (JSON body) AND in custom email
headers so that each endpoint can filter the shared mailbox for
messages addressed to itself.
"""

import uuid
import json
from datetime import datetime, timezone


PROTOCOL_VERSION = "1.0"

# Message types
MSG_DATA = "DATA"
MSG_ACK = "ACK"
MSG_NACK = "NACK"
MSG_ATTACH_ACK = "ATTACH_ACK"   # Confirms the receiver downloaded the attachment

# Subject prefix used for filtering protocol emails
SUBJECT_PREFIX = "[BEIS]"

# Custom email headers for endpoint identification in shared mailbox
HEADER_SENDER_ID = "X-BEIS-Sender"
HEADER_RECIPIENT_ID = "X-BEIS-Recipient"


def create_message_id() -> str:
    """Generate a globally unique message identifier."""
    return str(uuid.uuid4())


def build_envelope(
    msg_type: str,
    sender_id: str,
    recipient_id: str,
    payload: str | None = None,
    correlation_id: str | None = None,
    protocol_version: str = PROTOCOL_VERSION,
    nack_reason: str | None = None,
    has_attachment: bool = False,
    attachment_filename: str | None = None,
) -> dict:
    """Build a transport envelope dictionary."""
    envelope = {
        "protocol_version": protocol_version,
        "message_type": msg_type,
        "message_id": create_message_id(),
        "correlation_id": correlation_id,
        "sender_endpoint_id": sender_id,
        "recipient_endpoint_id": recipient_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
        "has_attachment": has_attachment,
        "attachment_filename": attachment_filename,
    }
    if nack_reason:
        envelope["nack_reason"] = nack_reason
    return envelope


def serialize_envelope(envelope: dict) -> str:
    """Serialize an envelope to JSON string."""
    return json.dumps(envelope, indent=2)


def deserialize_envelope(raw: str) -> dict | None:
    """Deserialize a JSON string into an envelope dict. Returns None on failure."""
    try:
        data = json.loads(raw)
        # Validate mandatory fields
        required = [
            "protocol_version",
            "message_type",
            "message_id",
            "sender_endpoint_id",
            "recipient_endpoint_id",
            "timestamp",
        ]
        for field in required:
            if field not in data:
                return None
        return data
    except (json.JSONDecodeError, TypeError):
        return None


def build_email_subject(msg_type: str, message_id: str, sender_id: str, recipient_id: str) -> str:
    """Build a structured email subject for protocol filtering.

    Format: [BEIS] <sender_id> -> <recipient_id> <msg_type> <message_id>

    The sender and recipient endpoint IDs are embedded in the subject
    so that endpoints sharing a single mailbox can quickly identify
    relevant messages before parsing the full body.
    """
    return f"{SUBJECT_PREFIX} {sender_id} -> {recipient_id} {msg_type} {message_id}"


def is_protocol_subject(subject: str) -> bool:
    """Check if an email subject belongs to this protocol."""
    return subject.strip().startswith(SUBJECT_PREFIX)
