from __future__ import annotations
"""
Bidirectional Email Interface — MVP
State store — JSON file backed, survives restarts.
"""

import os
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("app")

STATE_FILE = "state.json"

# Outbound states
OUT_CREATED = "CREATED"
OUT_SENT = "SENT"
OUT_WAITING_FOR_ACK = "WAITING_FOR_ACK"
OUT_ACKNOWLEDGED = "ACKNOWLEDGED"
OUT_NACKED = "NACKED"
OUT_RETRY_PENDING = "RETRY_PENDING"
OUT_FAILED = "FAILED"

# Inbound states
IN_RECEIVED = "RECEIVED"
IN_ACCEPTED = "ACCEPTED"
IN_REJECTED = "REJECTED"
IN_DUPLICATE = "DUPLICATE"
IN_RESPONSE_SENT = "RESPONSE_SENT"
IN_ATTACH_PENDING = "ATTACH_PENDING"       # ACK sent, attachment awaiting download
IN_ATTACH_DOWNLOADED = "ATTACH_DOWNLOADED"  # Attachment saved, ATTACH_ACK sent


class StateStore:
    """Persistent JSON-backed state store for message tracking."""

    def __init__(self, state_dir: str = "."):
        self.path = os.path.join(state_dir, STATE_FILE)
        self.data = {"outbound": {}, "inbound": {}, "seen_ids": []}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    self.data = json.load(f)
                logger.info("State loaded from %s", self.path)
            except (json.JSONDecodeError, IOError) as e:
                logger.error("Failed to load state file: %s", e)
                # Start fresh
                self.data = {"outbound": {}, "inbound": {}, "seen_ids": []}

    def _save(self):
        try:
            with open(self.path, "w") as f:
                json.dump(self.data, f, indent=2)
        except IOError as e:
            logger.error("Failed to save state file: %s", e)

    # --- Outbound ---

    def record_outbound(self, message_id: str, envelope: dict, state: str = OUT_CREATED):
        """Record a new outbound message."""
        self.data["outbound"][message_id] = {
            "envelope": envelope,
            "state": state,
            "retry_count": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save()
        logger.info("Outbound message %s recorded as %s", message_id, state)

    def update_outbound_state(self, message_id: str, state: str):
        """Update outbound message state."""
        if message_id in self.data["outbound"]:
            self.data["outbound"][message_id]["state"] = state
            self.data["outbound"][message_id]["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save()
            logger.info("Outbound message %s → %s", message_id, state)

    def increment_retry(self, message_id: str):
        """Increment retry counter for an outbound message."""
        if message_id in self.data["outbound"]:
            self.data["outbound"][message_id]["retry_count"] += 1
            self._save()

    def get_outbound(self, message_id: str) -> dict | None:
        return self.data["outbound"].get(message_id)

    def get_outbound_by_state(self, state: str) -> list[tuple[str, dict]]:
        """Return list of (message_id, record) with the given state."""
        return [
            (mid, rec)
            for mid, rec in self.data["outbound"].items()
            if rec["state"] == state
        ]

    # --- Inbound ---

    def is_duplicate(self, message_id: str) -> bool:
        return message_id in self.data["seen_ids"]

    def record_inbound(self, message_id: str, envelope: dict, state: str = IN_RECEIVED):
        """Record a new inbound message."""
        self.data["inbound"][message_id] = {
            "envelope": envelope,
            "state": state,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        if message_id not in self.data["seen_ids"]:
            self.data["seen_ids"].append(message_id)
        self._save()
        logger.info("Inbound message %s recorded as %s", message_id, state)

    def update_inbound_state(self, message_id: str, state: str):
        if message_id in self.data["inbound"]:
            self.data["inbound"][message_id]["state"] = state
            self._save()
            logger.info("Inbound message %s → %s", message_id, state)

    def get_inbound(self, message_id: str) -> dict | None:
        return self.data["inbound"].get(message_id)

    def get_inbound_by_state(self, state: str) -> list[tuple[str, dict]]:
        """Return list of (message_id, record) with the given inbound state."""
        return [
            (mid, rec)
            for mid, rec in self.data["inbound"].items()
            if rec["state"] == state
        ]

    def store_attachment_data(self, message_id: str, attachment_bytes_hex: str):
        """Store raw attachment bytes (hex-encoded) for later download."""
        if message_id in self.data["inbound"]:
            self.data["inbound"][message_id]["attachment_data"] = attachment_bytes_hex
            self._save()

    def get_attachment_data(self, message_id: str) -> str | None:
        """Retrieve stored hex-encoded attachment bytes, or None."""
        rec = self.data["inbound"].get(message_id)
        if rec:
            return rec.get("attachment_data")
        return None

    def clear_attachment_data(self, message_id: str):
        """Remove raw attachment bytes from state after download to save space."""
        if message_id in self.data["inbound"]:
            self.data["inbound"][message_id].pop("attachment_data", None)
            self._save()
