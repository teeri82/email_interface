#!/usr/bin/env python3
from __future__ import annotations
"""
Bidirectional Email Interface — MVP
Main CLI application.

Usage:
    python main.py                  # Start with default config.json in cwd
    python main.py -c myconfig.json # Start with custom config path

CLI commands (once running):
    send <peer_id> <payload>   — Send a DATA message to a peer
    status                     — Show outbound/inbound message summary
    peers                      — List configured peers
    quit / exit                — Shut down gracefully
    help                       — Show available commands
"""

import sys
import os
import cmd
import shlex
import threading
import time
import logging
import argparse
from datetime import datetime, timezone, timedelta

from config_loader import load_config
from envelope import (
    build_envelope,
    serialize_envelope,
    MSG_DATA,
    MSG_ACK,
    MSG_NACK,
    MSG_ATTACH_ACK,
)
from state_store import (
    StateStore,
    OUT_CREATED,
    OUT_SENT,
    OUT_WAITING_FOR_ACK,
    OUT_ACKNOWLEDGED,
    OUT_NACKED,
    OUT_RETRY_PENDING,
    OUT_FAILED,
    IN_RECEIVED,
    IN_ACCEPTED,
    IN_DUPLICATE,
    IN_RESPONSE_SENT,
    IN_ATTACH_PENDING,
    IN_ATTACH_DOWNLOADED,
)
from transport import send_email, fetch_protocol_emails
from cleanup import delete_sent_email, cleanup_acknowledged, cleanup_expired

# Subdirectories for attachments
OUT_DIR = "out"
IN_DIR = "in"


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def setup_logging():
    """Configure two log files: app.log (application) and communication.log (message traffic)."""
    # --- Application logger ---
    app_logger = logging.getLogger("app")
    app_logger.setLevel(logging.DEBUG)

    app_handler = logging.FileHandler("app.log", encoding="utf-8")
    app_handler.setLevel(logging.DEBUG)
    app_handler.setFormatter(
        logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s")
    )
    app_logger.addHandler(app_handler)

    # Also log warnings+ to stderr so operator sees critical issues
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(
        logging.Formatter("%(levelname)s: %(message)s")
    )
    app_logger.addHandler(console_handler)

    # --- Communication logger ---
    comm_logger = logging.getLogger("comm")
    comm_logger.setLevel(logging.DEBUG)

    comm_handler = logging.FileHandler("communication.log", encoding="utf-8")
    comm_handler.setLevel(logging.DEBUG)
    comm_handler.setFormatter(
        logging.Formatter("%(asctime)s  %(message)s")
    )
    comm_logger.addHandler(comm_handler)


app_log = logging.getLogger("app")
comm_log = logging.getLogger("comm")


# ---------------------------------------------------------------------------
# Inbound processing
# ---------------------------------------------------------------------------

def process_inbound(config: dict, state: StateStore):
    """Fetch protocol emails and process each one."""
    envelopes = fetch_protocol_emails(config)
    if not envelopes:
        return

    my_id = config["endpoint_id"]

    for env in envelopes:
        msg_type = env.get("message_type")
        msg_id = env.get("message_id")
        sender = env.get("sender_endpoint_id")
        corr_id = env.get("correlation_id")

        # Ignore messages not addressed to us (if recipient_endpoint_id is set)
        recipient = env.get("recipient_endpoint_id")
        if recipient and recipient != my_id:
            app_log.warning(
                "Ignoring message %s addressed to '%s' (we are '%s')",
                msg_id, recipient, my_id,
            )
            continue

        if msg_type == MSG_DATA:
            _handle_inbound_data(config, state, env)
        elif msg_type == MSG_ACK:
            _handle_inbound_ack(config, state, env)
        elif msg_type == MSG_NACK:
            _handle_inbound_nack(config, state, env)
        elif msg_type == MSG_ATTACH_ACK:
            _handle_inbound_attach_ack(config, state, env)
        else:
            app_log.warning("Unknown message type '%s' in message %s", msg_type, msg_id)


def _handle_inbound_data(config: dict, state: StateStore, env: dict):
    """Process an inbound DATA message: detect duplicates, send ACK.

    If the message carries an attachment the ACK is sent immediately
    (confirming message receipt) but the attachment is held in state as
    ATTACH_PENDING until the operator explicitly downloads it.
    """
    msg_id = env["message_id"]
    sender = env["sender_endpoint_id"]
    payload = env.get("payload", "")
    has_attachment = env.get("has_attachment", False)
    attach_name = env.get("attachment_filename") or env.get("_attachment_filename") or ""
    my_id = config["endpoint_id"]

    comm_log.info(
        "RECV  DATA  from=%s  msg_id=%s  payload=%s%s",
        sender, msg_id, _truncate(payload, 120),
        f"  attachment={attach_name}" if has_attachment else "",
    )

    # Duplicate detection
    if state.is_duplicate(msg_id):
        app_log.info("Duplicate DATA message %s — re-sending ACK", msg_id)
        env.pop("_attachment_data", None)
        env.pop("_attachment_filename", None)
        state.record_inbound(msg_id, env, IN_DUPLICATE)
        _send_ack(config, state, env)
        return

    # Extract transient attachment data BEFORE persisting the envelope in state
    # (raw bytes are not JSON-serializable and must not leak into state.json)
    attachment_bytes: bytes | None = env.pop("_attachment_data", None)
    env.pop("_attachment_filename", None)

    # Record inbound (envelope is now clean of transient keys)
    state.record_inbound(msg_id, env, IN_RECEIVED)
    state.update_inbound_state(msg_id, IN_ACCEPTED)

    if has_attachment and attachment_bytes is not None:
        state.store_attachment_data(msg_id, attachment_bytes.hex())
        state.update_inbound_state(msg_id, IN_ATTACH_PENDING)
        print(f"\n[MESSAGE+FILE] From {sender}: {payload}")
        print(f"  📎 Attachment: {attach_name}  (use 'dl {msg_id[:8]}' to download)")
        print("> ", end="", flush=True)
    else:
        # Plain text message — save directly to in/<msg_id>/
        _save_plain_message(msg_id, sender, payload)
        print(f"\n[MESSAGE] From {sender}: {payload}")
        print("> ", end="", flush=True)

    # Always send ACK (confirms message receipt)
    _send_ack(config, state, env)


def _send_ack(config: dict, state: StateStore, original_env: dict):
    """Build and send an ACK for the given DATA envelope."""
    my_id = config["endpoint_id"]
    sender = original_env["sender_endpoint_id"]
    msg_id = original_env["message_id"]

    ack = build_envelope(
        msg_type=MSG_ACK,
        sender_id=my_id,
        recipient_id=sender,
        correlation_id=msg_id,
    )

    if sender not in config["peers"]:
        app_log.error("Cannot send ACK — peer '%s' not in peer list", sender)
        return

    success = send_email(config, ack)
    if success:
        comm_log.info("SEND  ACK   to=%s  corr_id=%s  ack_msg_id=%s", sender, msg_id, ack["message_id"])
        state.update_inbound_state(msg_id, IN_RESPONSE_SENT)
    else:
        app_log.error("Failed to send ACK for message %s", msg_id)


def _handle_inbound_ack(config: dict, state: StateStore, env: dict):
    """Process an inbound ACK — correlate with outbound message."""
    corr_id = env.get("correlation_id")
    sender = env["sender_endpoint_id"]

    comm_log.info(
        "RECV  ACK   from=%s  corr_id=%s  ack_msg_id=%s",
        sender, corr_id, env["message_id"],
    )

    if not corr_id:
        app_log.warning("Received ACK without correlation_id from %s", sender)
        return

    outbound = state.get_outbound(corr_id)
    if outbound is None:
        app_log.warning("Received ACK for unknown outbound message %s", corr_id)
        return

    state.update_outbound_state(corr_id, OUT_ACKNOWLEDGED)
    print(f"\n[ACK] Message {corr_id} acknowledged by {sender}")
    print("> ", end="", flush=True)

    # Trigger cleanup: for text-only messages, delete the sent email now.
    # For attachment messages, wait until ATTACH_ACK is also received.
    envelope = outbound["envelope"]
    if not envelope.get("has_attachment"):
        _try_cleanup(config, state, corr_id)


def _handle_inbound_nack(config: dict, state: StateStore, env: dict):
    """Process an inbound NACK — mark outbound as NACKED."""
    corr_id = env.get("correlation_id")
    sender = env["sender_endpoint_id"]
    reason = env.get("nack_reason", "unknown")

    comm_log.info(
        "RECV  NACK  from=%s  corr_id=%s  reason=%s",
        sender, corr_id, reason,
    )

    if not corr_id:
        app_log.warning("Received NACK without correlation_id from %s", sender)
        return

    outbound = state.get_outbound(corr_id)
    if outbound is None:
        app_log.warning("Received NACK for unknown outbound message %s", corr_id)
        return

    state.update_outbound_state(corr_id, OUT_NACKED)
    print(f"\n[NACK] Message {corr_id} rejected by {sender}: {reason}")
    print("> ", end="", flush=True)

    # NACK means rejected — clean up the sent email
    _try_cleanup(config, state, corr_id)


def _handle_inbound_attach_ack(config: dict, state: StateStore, env: dict):
    """Process an inbound ATTACH_ACK — the receiver downloaded our attachment."""
    corr_id = env.get("correlation_id")
    sender = env["sender_endpoint_id"]

    comm_log.info(
        "RECV  ATTACH_ACK  from=%s  corr_id=%s  msg_id=%s",
        sender, corr_id, env["message_id"],
    )

    if not corr_id:
        app_log.warning("Received ATTACH_ACK without correlation_id from %s", sender)
        return

    outbound = state.get_outbound(corr_id)
    if outbound is None:
        app_log.warning("Received ATTACH_ACK for unknown outbound message %s", corr_id)
        return

    # Record that the attachment has been downloaded
    state.set_attach_ack_received(corr_id)

    # Already ACKNOWLEDGED by the message ACK — this is the second confirmation
    print(f"\n[ATTACH_ACK] Attachment for message {corr_id[:8]}… downloaded by {sender}")
    print("> ", end="", flush=True)

    # Both ACK and ATTACH_ACK received — now eligible for cleanup
    _try_cleanup(config, state, corr_id)


def _try_cleanup(config: dict, state: StateStore, message_id: str):
    """Attempt to delete the sent email for an outbound message (best-effort).

    Called when a message reaches a state where deletion is appropriate.
    Failures are logged but never prevent state transitions.
    """
    record = state.get_outbound(message_id)
    if record is None or record.get("email_deleted"):
        return

    my_id = config["endpoint_id"]
    envelope = record["envelope"]
    recipient_id = envelope["recipient_endpoint_id"]

    success = delete_sent_email(config, message_id, my_id, recipient_id)
    state.mark_email_deleted(message_id, success)
    if success:
        app_log.info("Sent email deleted for message %s", message_id)


def _save_plain_message(msg_id: str, sender: str, payload: str):
    """Save a plain (no-attachment) message into in/<msg_id>/."""
    msg_dir = os.path.join(IN_DIR, msg_id)
    os.makedirs(msg_dir, exist_ok=True)

    meta_path = os.path.join(msg_dir, "message.txt")
    with open(meta_path, "w", encoding="utf-8") as f:
        f.write(f"From: {sender}\n")
        f.write(f"Message-ID: {msg_id}\n")
        f.write(f"---\n")
        f.write(payload or "")
    app_log.info("Plain message saved to %s", msg_dir)


# ---------------------------------------------------------------------------
# Retry scheduler
# ---------------------------------------------------------------------------

def retry_check(config: dict, state: StateStore):
    """Check for messages needing retry and resend them."""
    timeout = config.get("ack_timeout_seconds", 60)
    max_retries = config.get("retry_count", 3)
    now = datetime.now(timezone.utc)

    # Check WAITING_FOR_ACK messages that have timed out
    waiting = state.get_outbound_by_state(OUT_WAITING_FOR_ACK)
    for msg_id, record in waiting:
        updated = datetime.fromisoformat(record["updated_at"])
        elapsed = (now - updated).total_seconds()
        if elapsed < timeout:
            continue

        retries = record.get("retry_count", 0)
        if retries >= max_retries:
            state.update_outbound_state(msg_id, OUT_FAILED)
            comm_log.info("FAIL  DATA  msg_id=%s  retries_exhausted=%d", msg_id, retries)
            app_log.warning("Message %s FAILED — max retries (%d) exhausted", msg_id, max_retries)
            print(f"\n[FAILED] Message {msg_id} — retries exhausted")
            print("> ", end="", flush=True)
            # Clean up the sent email from the mailbox
            _try_cleanup(config, state, msg_id)
            continue

        # Retry
        _retry_send(config, state, msg_id, record)


def _retry_send(config: dict, state: StateStore, msg_id: str, record: dict):
    """Resend an outbound message as a retry."""
    envelope = record["envelope"]
    recipient_id = envelope["recipient_endpoint_id"]

    if recipient_id not in config["peers"]:
        app_log.error("Cannot retry message %s — peer '%s' not in peer list", msg_id, recipient_id)
        state.update_outbound_state(msg_id, OUT_FAILED)
        return

    state.increment_retry(msg_id)
    retry_num = record["retry_count"] + 1  # after increment

    app_log.info("Retrying message %s (attempt %d)", msg_id, retry_num)
    comm_log.info("RETRY DATA  to=%s  msg_id=%s  attempt=%d", recipient_id, msg_id, retry_num)

    success = send_email(config, envelope)
    if success:
        state.update_outbound_state(msg_id, OUT_WAITING_FOR_ACK)
    else:
        app_log.error("Retry send failed for message %s", msg_id)
        state.update_outbound_state(msg_id, OUT_WAITING_FOR_ACK)  # will retry again next cycle


# ---------------------------------------------------------------------------
# Background worker thread
# ---------------------------------------------------------------------------

class BackgroundWorker(threading.Thread):
    """Daemon thread that periodically polls for inbound messages and checks retries."""

    def __init__(self, config: dict, state: StateStore):
        super().__init__(daemon=True)
        self.config = config
        self.state = state
        self._stop_event = threading.Event()

    def run(self):
        interval = self.config.get("polling_interval_seconds", 10)
        app_log.info("Background worker started (poll every %ds)", interval)
        cycle = 0
        while not self._stop_event.is_set():
            try:
                process_inbound(self.config, self.state)
            except Exception as e:
                app_log.error("Error in inbound processing: %s", e)
            try:
                retry_check(self.config, self.state)
            except Exception as e:
                app_log.error("Error in retry check: %s", e)
            # Run periodic cleanup every 6 cycles (catch-all for missed deletions + expiry)
            cycle += 1
            if cycle % 6 == 0:
                try:
                    cleanup_acknowledged(self.config, self.state)
                    cleanup_expired(self.config, self.state)
                except Exception as e:
                    app_log.error("Error in periodic cleanup: %s", e)
            self._stop_event.wait(interval)

    def stop(self):
        self._stop_event.set()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

class BeisCLI(cmd.Cmd):
    """Interactive command-line interface for the BEIS endpoint."""

    intro = (
        "==============================================\n"
        "  Bidirectional Email Interface — MVP\n"
        "==============================================\n"
        "Type 'help' for available commands.\n"
    )
    prompt = "> "

    def __init__(self, config: dict, state: StateStore, worker: BackgroundWorker):
        super().__init__()
        self.config = config
        self.state = state
        self.worker = worker

    # --- send ---

    def do_send(self, arg: str):
        """Send a DATA message: send <peer_id> <payload> [-f <filename>]"""
        # Parse -f flag using shlex for proper quoting support
        try:
            tokens = shlex.split(arg)
        except ValueError:
            tokens = arg.strip().split()

        attachment_file = None
        # Extract -f <filename> if present
        if "-f" in tokens:
            idx = tokens.index("-f")
            if idx + 1 >= len(tokens):
                print("Usage: send <peer_id> <payload> [-f <filename>]")
                print("  -f requires a filename from the 'out/' directory")
                return
            attachment_file = tokens[idx + 1]
            tokens = tokens[:idx] + tokens[idx + 2:]  # remove -f and filename

        if len(tokens) < 2:
            print("Usage: send <peer_id> <payload> [-f <filename>]")
            return

        peer_id = tokens[0]
        payload = " ".join(tokens[1:])

        if peer_id not in self.config["peers"]:
            print(f"Unknown peer '{peer_id}'. Use 'peers' to list configured peers.")
            return

        # Resolve attachment path from out/ directory
        attachment_path = None
        if attachment_file:
            attachment_path = os.path.join(OUT_DIR, attachment_file)
            if not os.path.isfile(attachment_path):
                print(f"File not found: {attachment_path}")
                print(f"Place files in the '{OUT_DIR}/' directory before sending.")
                return

        my_id = self.config["endpoint_id"]
        envelope = build_envelope(
            msg_type=MSG_DATA,
            sender_id=my_id,
            recipient_id=peer_id,
            payload=payload,
            has_attachment=attachment_path is not None,
            attachment_filename=os.path.basename(attachment_path) if attachment_path else None,
        )
        msg_id = envelope["message_id"]

        # Record in state
        self.state.record_outbound(msg_id, envelope, OUT_CREATED)

        # Send — all endpoints share the same email; recipient is identified in headers/body
        success = send_email(self.config, envelope, attachment_path=attachment_path)
        if success:
            self.state.update_outbound_state(msg_id, OUT_WAITING_FOR_ACK)
            comm_log.info(
                "SEND  DATA  to=%s  msg_id=%s  payload=%s%s",
                peer_id, msg_id, _truncate(payload, 120),
                f"  attachment={os.path.basename(attachment_path)}" if attachment_path else "",
            )
            if attachment_path:
                print(f"Message + attachment sent (id: {msg_id}). Waiting for ACK…")
            else:
                print(f"Message sent (id: {msg_id}). Waiting for ACK…")
        else:
            self.state.update_outbound_state(msg_id, OUT_FAILED)
            comm_log.info("FAIL  DATA  to=%s  msg_id=%s  send_error", peer_id, msg_id)
            print("Failed to send message. Check app.log for details.")

    def complete_send(self, text, line, begidx, endidx):
        """Tab-complete peer IDs for the send command."""
        peers = list(self.config["peers"])
        if text:
            return [p for p in peers if p.startswith(text)]
        return peers

    # --- status ---

    def do_status(self, arg: str):
        """Show message status summary."""
        out = self.state.data.get("outbound", {})
        inb = self.state.data.get("inbound", {})

        print(f"\n--- Outbound ({len(out)} messages) ---")
        if out:
            for mid, rec in out.items():
                env = rec["envelope"]
                attach_str = ""
                if env.get("has_attachment"):
                    attach_str = f"  📎 {env.get('attachment_filename', '?')}"
                print(
                    f"  {mid[:8]}…  {rec['state']:<18}  to={env['recipient_endpoint_id']}"
                    f"  retries={rec.get('retry_count', 0)}  payload={_truncate(env.get('payload', ''), 40)}"
                    f"{attach_str}"
                )
        else:
            print("  (none)")

        print(f"\n--- Inbound ({len(inb)} messages) ---")
        if inb:
            for mid, rec in inb.items():
                env = rec["envelope"]
                attach_str = ""
                if env.get("has_attachment"):
                    fname = env.get("attachment_filename", "?")
                    if rec["state"] == IN_ATTACH_PENDING:
                        attach_str = f"  📎 {fname} [PENDING]"
                    elif rec["state"] == IN_ATTACH_DOWNLOADED:
                        attach_str = f"  📎 {fname} [DOWNLOADED]"
                    else:
                        attach_str = f"  📎 {fname}"
                print(
                    f"  {mid[:8]}…  {rec['state']:<18}  from={env['sender_endpoint_id']}"
                    f"  payload={_truncate(env.get('payload', ''), 40)}"
                    f"{attach_str}"
                )
        else:
            print("  (none)")
        print()

    # --- dlpend (list pending attachment downloads) ---

    def do_dlpend(self, arg: str):
        """List messages with pending attachment downloads."""
        pending = self.state.get_inbound_by_state(IN_ATTACH_PENDING)
        if not pending:
            print("No pending attachment downloads.")
            return
        print(f"\n--- Pending Attachment Downloads ({len(pending)}) ---")
        for mid, rec in pending:
            env = rec["envelope"]
            fname = env.get("attachment_filename", "unknown")
            sender = env["sender_endpoint_id"]
            payload = env.get("payload", "")
            print(f"  {mid[:8]}…  from={sender}  📎 {fname}  payload={_truncate(payload, 50)}")
        print(f"\nUse 'dl <msg_id_prefix>' to download an attachment.")
        print()

    # --- dl (download a pending attachment) ---

    def do_dl(self, arg: str):
        """Download a pending attachment: dl <msg_id_prefix>"""
        prefix = arg.strip()
        if not prefix:
            print("Usage: dl <msg_id_prefix>")
            print("  Use 'dlpend' to list pending downloads.")
            return

        # Find the matching message by prefix
        pending = self.state.get_inbound_by_state(IN_ATTACH_PENDING)
        matches = [(mid, rec) for mid, rec in pending if mid.startswith(prefix)]

        if not matches:
            print(f"No pending attachment found matching '{prefix}'.")
            print("  Use 'dlpend' to list pending downloads.")
            return
        if len(matches) > 1:
            print(f"Ambiguous prefix '{prefix}' — matches {len(matches)} messages:")
            for mid, _ in matches:
                print(f"  {mid[:12]}…")
            print("  Provide a longer prefix.")
            return

        msg_id, record = matches[0]
        env = record["envelope"]
        sender = env["sender_endpoint_id"]
        payload = env.get("payload", "")
        fname = env.get("attachment_filename", "unnamed_attachment")

        # Retrieve attachment bytes from state
        hex_data = self.state.get_attachment_data(msg_id)
        if not hex_data:
            print(f"Error: attachment data not found for message {msg_id[:8]}…")
            app_log.error("Attachment data missing from state for message %s", msg_id)
            return

        attachment_bytes = bytes.fromhex(hex_data)

        # Save into in/<msg_id>/
        msg_dir = os.path.join(IN_DIR, msg_id)
        os.makedirs(msg_dir, exist_ok=True)

        # Write message text
        meta_path = os.path.join(msg_dir, "message.txt")
        with open(meta_path, "w", encoding="utf-8") as f:
            f.write(f"From: {sender}\n")
            f.write(f"Message-ID: {msg_id}\n")
            f.write(f"Attachment: {fname}\n")
            f.write(f"---\n")
            f.write(payload or "")

        # Write attachment file
        attach_path = os.path.join(msg_dir, fname)
        with open(attach_path, "wb") as f:
            f.write(attachment_bytes)

        # Clean up hex data from state to save space
        self.state.clear_attachment_data(msg_id)
        self.state.update_inbound_state(msg_id, IN_ATTACH_DOWNLOADED)

        print(f"✅ Saved to {msg_dir}/")
        print(f"   message.txt  ({len(payload)} chars)")
        print(f"   {fname}  ({len(attachment_bytes)} bytes)")
        app_log.info("Attachment downloaded: %s → %s", msg_id, msg_dir)
        comm_log.info("DL    ATTACH  msg_id=%s  file=%s  bytes=%d", msg_id, fname, len(attachment_bytes))

        # Send ATTACH_ACK to the sender
        my_id = self.config["endpoint_id"]
        attach_ack = build_envelope(
            msg_type=MSG_ATTACH_ACK,
            sender_id=my_id,
            recipient_id=sender,
            correlation_id=msg_id,
        )

        if sender in self.config["peers"]:
            success = send_email(self.config, attach_ack)
            if success:
                comm_log.info(
                    "SEND  ATTACH_ACK  to=%s  corr_id=%s  msg_id=%s",
                    sender, msg_id, attach_ack["message_id"],
                )
            else:
                app_log.error("Failed to send ATTACH_ACK for message %s", msg_id)
        else:
            app_log.error("Cannot send ATTACH_ACK — peer '%s' not in peer list", sender)

    def complete_dl(self, text, line, begidx, endidx):
        """Tab-complete pending message IDs for the dl command."""
        pending = self.state.get_inbound_by_state(IN_ATTACH_PENDING)
        ids = [mid[:8] for mid, _ in pending]
        if text:
            return [i for i in ids if i.startswith(text)]
        return ids

    # --- peers ---

    def do_peers(self, arg: str):
        """List configured peers."""
        peers = self.config.get("peers", [])
        if not peers:
            print("No peers configured.")
            return
        print(f"\nConfigured peers (shared email: {self.config['email_address']}):")
        for pid in peers:
            print(f"  {pid}")
        print()

    # --- info ---

    def do_info(self, arg: str):
        """Show this endpoint's configuration."""
        print(f"\n  Endpoint ID : {self.config['endpoint_id']}")
        print(f"  Email       : {self.config['email_address']}")
        print(f"  SMTP        : {self.config['smtp_host']}:{self.config['smtp_port']}")
        print(f"  IMAP        : {self.config['imap_host']}:{self.config['imap_port']}")
        print(f"  Poll interval: {self.config['polling_interval_seconds']}s")
        print(f"  ACK timeout : {self.config['ack_timeout_seconds']}s")
        print(f"  Max retries : {self.config['retry_count']}")
        print()

    # --- quit/exit ---

    def do_quit(self, arg: str):
        """Shut down the application."""
        print("Shutting down…")
        self.worker.stop()
        app_log.info("Application shutdown requested by user")
        return True

    def do_exit(self, arg: str):
        """Shut down the application."""
        return self.do_quit(arg)

    def do_EOF(self, arg: str):
        """Handle Ctrl+D."""
        print()
        return self.do_quit(arg)

    # --- help override for nicer output ---

    def do_help(self, arg: str):
        """Show available commands."""
        if arg:
            super().do_help(arg)
            return
        print("\nAvailable commands:")
        print("  send <peer_id> <payload>        — Send a text message to a peer")
        print("  send <peer_id> <payload> -f <file> — Send a message with attachment from out/")
        print("  status                           — Show message status summary")
        print("  dlpend                           — List pending attachment downloads")
        print("  dl <msg_id_prefix>               — Download a pending attachment to in/")
        print("  peers                            — List configured peers")
        print("  info                             — Show endpoint configuration")
        print("  quit / exit                      — Shut down gracefully")
        print("  help [command]                   — Show help")
        print()


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _truncate(s: str, max_len: int = 80) -> str:
    if not s:
        return ""
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Bidirectional Email Interface — MVP")
    parser.add_argument(
        "-c", "--config",
        default="config.json",
        help="Path to configuration file (default: config.json)",
    )
    args = parser.parse_args()

    # Set up logging first
    setup_logging()
    app_log.info("=" * 50)
    app_log.info("BEIS MVP starting up")

    # Load config
    try:
        config = load_config(args.config)
    except (FileNotFoundError, ValueError) as e:
        print(f"Configuration error: {e}")
        sys.exit(1)

    app_log.info("Endpoint ID: %s", config["endpoint_id"])
    app_log.info("Email: %s", config["email_address"])
    app_log.info("Peers: %s", list(config["peers"]))

    # Ensure out/ and in/ directories exist
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(IN_DIR, exist_ok=True)

    # Initialise state store
    state = StateStore()

    # Start background worker
    worker = BackgroundWorker(config, state)
    worker.start()
    app_log.info("Background poller started")

    # Run interactive CLI
    cli = BeisCLI(config, state, worker)
    try:
        cli.cmdloop()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        worker.stop()
        app_log.info("Application interrupted by Ctrl+C")

    app_log.info("BEIS MVP shut down")


if __name__ == "__main__":
    main()
