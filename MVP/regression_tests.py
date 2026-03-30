#!/usr/bin/env python3
from __future__ import annotations
"""
BEIS MVP — Regression Test Suite
=================================
Automated + semi-automated tests to verify that the email-deletion
feature branch has not broken existing MVP functionality.

Tests are grouped by module and risk level.
Run from inside an endpoint directory (with config.json):

    cd test1 && python ../regression_tests.py

Tests that hit real IMAP/SMTP are marked [LIVE] and need valid credentials.
Tests that are pure logic are marked [UNIT].
"""

import os
import sys
import json
import time
import copy
import tempfile
import shutil
import logging
from datetime import datetime, timezone, timedelta

# Ensure parent dir is on the path so we can import MVP modules
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from config_loader import load_config, DEFAULT_CONFIG
from envelope import (
    build_envelope,
    serialize_envelope,
    deserialize_envelope,
    build_email_subject,
    is_protocol_subject,
    MSG_DATA,
    MSG_ACK,
    MSG_NACK,
    MSG_ATTACH_ACK,
    SUBJECT_PREFIX,
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

# ──────────────────────────────────────────────────────────────
# Test infrastructure
# ──────────────────────────────────────────────────────────────

PASS = 0
FAIL = 0
SKIP = 0
RESULTS: list[tuple[str, str, str]] = []  # (id, status, description)


def _report(test_id: str, passed: bool, desc: str, detail: str = ""):
    global PASS, FAIL
    status = "PASS" if passed else "FAIL"
    if passed:
        PASS += 1
    else:
        FAIL += 1
    icon = "✅" if passed else "❌"
    RESULTS.append((test_id, status, desc))
    print(f"  {icon} {test_id}: {desc}")
    if detail:
        print(f"       {detail}")


def _skip(test_id: str, desc: str, reason: str):
    global SKIP
    SKIP += 1
    RESULTS.append((test_id, "SKIP", desc))
    print(f"  ⏭️  {test_id}: {desc} — SKIPPED ({reason})")


def _section(title: str):
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


# ──────────────────────────────────────────────────────────────
# R1: config_loader — backward compatibility
# ──────────────────────────────────────────────────────────────

def test_r1_config():
    _section("R1: config_loader backward compatibility")

    # R1.1: Old config without email_max_lifetime_days still loads
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({
            "endpoint_id": "test-ep",
            "email_address": "x@x.com",
            "email_password": "pass",
            "smtp_host": "smtp.gmail.com",
            "imap_host": "imap.gmail.com",
            "peers": ["peer1"],
        }, f)
        f.flush()
        try:
            cfg = load_config(f.name)
            has_lifetime = "email_max_lifetime_days" in cfg
            _report("R1.1", has_lifetime and cfg["email_max_lifetime_days"] == 30,
                    "[UNIT] Old config gets email_max_lifetime_days=30 default",
                    f"Got: {cfg.get('email_max_lifetime_days')}")
        except Exception as e:
            _report("R1.1", False, "[UNIT] Old config loads without email_max_lifetime_days",
                    f"Exception: {e}")
        finally:
            os.unlink(f.name)

    # R1.2: Config WITH email_max_lifetime_days=0 is respected
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({
            "endpoint_id": "test-ep",
            "email_address": "x@x.com",
            "email_password": "pass",
            "smtp_host": "smtp.gmail.com",
            "imap_host": "imap.gmail.com",
            "peers": ["peer1"],
            "email_max_lifetime_days": 0,
        }, f)
        f.flush()
        try:
            cfg = load_config(f.name)
            _report("R1.2", cfg["email_max_lifetime_days"] == 0,
                    "[UNIT] Config with email_max_lifetime_days=0 is preserved",
                    f"Got: {cfg.get('email_max_lifetime_days')}")
        except Exception as e:
            _report("R1.2", False, "[UNIT] Config with email_max_lifetime_days=0",
                    f"Exception: {e}")
        finally:
            os.unlink(f.name)

    # R1.3: All original required fields still enforced
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"endpoint_id": "test-ep"}, f)  # missing email_address, etc.
        f.flush()
        try:
            load_config(f.name)
            _report("R1.3", False,
                    "[UNIT] Missing required fields raises ValueError",
                    "No exception raised!")
        except ValueError:
            _report("R1.3", True,
                    "[UNIT] Missing required fields raises ValueError")
        except Exception as e:
            _report("R1.3", False,
                    "[UNIT] Missing required fields raises ValueError",
                    f"Wrong exception: {type(e).__name__}: {e}")
        finally:
            os.unlink(f.name)


# ──────────────────────────────────────────────────────────────
# R2: envelope — unchanged module sanity check
# ──────────────────────────────────────────────────────────────

def test_r2_envelope():
    _section("R2: envelope module integrity")

    # R2.1: build_envelope produces all required fields
    env = build_envelope(MSG_DATA, "sender", "recipient", payload="hello")
    required = ["protocol_version", "message_type", "message_id",
                "sender_endpoint_id", "recipient_endpoint_id", "timestamp"]
    all_present = all(k in env for k in required)
    _report("R2.1", all_present,
            "[UNIT] build_envelope includes all required fields")

    # R2.2: serialize → deserialize round-trip
    raw = serialize_envelope(env)
    restored = deserialize_envelope(raw)
    _report("R2.2", restored is not None and restored["message_id"] == env["message_id"],
            "[UNIT] serialize/deserialize round-trip preserves data")

    # R2.3: Subject generation and parsing
    subj = build_email_subject(MSG_DATA, "msg-123", "ep-A", "ep-B")
    _report("R2.3", is_protocol_subject(subj) and "msg-123" in subj,
            "[UNIT] build_email_subject / is_protocol_subject round-trip")

    # R2.4: Attachment fields in envelope
    env_a = build_envelope(MSG_DATA, "s", "r", payload="f",
                           has_attachment=True, attachment_filename="test.pdf")
    _report("R2.4", env_a["has_attachment"] is True and env_a["attachment_filename"] == "test.pdf",
            "[UNIT] Attachment fields preserved in envelope")


# ──────────────────────────────────────────────────────────────
# R3: state_store — existing methods still work + new fields don't break
# ──────────────────────────────────────────────────────────────

def test_r3_state_store():
    _section("R3: state_store regression")

    tmpdir = tempfile.mkdtemp()
    try:
        st = StateStore(state_dir=tmpdir)

        # R3.1: Outbound record/update/get cycle
        env = build_envelope(MSG_DATA, "s", "r", payload="test")
        mid = env["message_id"]
        st.record_outbound(mid, env, OUT_CREATED)
        rec = st.get_outbound(mid)
        _report("R3.1", rec is not None and rec["state"] == OUT_CREATED,
                "[UNIT] record_outbound → get_outbound works")

        # R3.2: State transitions
        st.update_outbound_state(mid, OUT_WAITING_FOR_ACK)
        _report("R3.2", st.get_outbound(mid)["state"] == OUT_WAITING_FOR_ACK,
                "[UNIT] update_outbound_state works")

        # R3.3: Retry counter
        st.increment_retry(mid)
        _report("R3.3", st.get_outbound(mid)["retry_count"] == 1,
                "[UNIT] increment_retry works")

        # R3.4: get_outbound_by_state
        results = st.get_outbound_by_state(OUT_WAITING_FOR_ACK)
        _report("R3.4", len(results) == 1 and results[0][0] == mid,
                "[UNIT] get_outbound_by_state returns correct records")

        # R3.5: Inbound record + duplicate detection
        in_env = build_envelope(MSG_DATA, "peer", "me", payload="in-test")
        in_id = in_env["message_id"]
        st.record_inbound(in_id, in_env, IN_RECEIVED)
        _report("R3.5", st.is_duplicate(in_id) and not st.is_duplicate("nonexistent"),
                "[UNIT] Duplicate detection works correctly")

        # R3.6: Inbound state transitions
        st.update_inbound_state(in_id, IN_ACCEPTED)
        _report("R3.6", st.get_inbound(in_id)["state"] == IN_ACCEPTED,
                "[UNIT] update_inbound_state works")

        # R3.7: Attachment data store/get/clear
        st.store_attachment_data(in_id, "deadbeef")
        got = st.get_attachment_data(in_id)
        _report("R3.7a", got == "deadbeef",
                "[UNIT] store_attachment_data / get_attachment_data works")
        st.clear_attachment_data(in_id)
        _report("R3.7b", st.get_attachment_data(in_id) is None,
                "[UNIT] clear_attachment_data removes data")

        # R3.8: New methods don't break existing records
        st.update_outbound_state(mid, OUT_ACKNOWLEDGED)
        st.mark_email_deleted(mid, True)
        rec_after = st.get_outbound(mid)
        _report("R3.8a", rec_after["state"] == OUT_ACKNOWLEDGED and rec_after.get("email_deleted") is True,
                "[UNIT] mark_email_deleted adds field without breaking record")
        st.set_attach_ack_received(mid)
        _report("R3.8b", st.get_outbound(mid).get("attach_ack_received") is True,
                "[UNIT] set_attach_ack_received adds field without breaking record")

        # R3.9: State persistence — reload from disk
        st2 = StateStore(state_dir=tmpdir)
        _report("R3.9", st2.get_outbound(mid)["state"] == OUT_ACKNOWLEDGED,
                "[UNIT] State survives reload from disk")

        # R3.10: Old state files without new fields load correctly
        # Simulate old state: remove email_deleted and attach_ack_received
        state_path = os.path.join(tmpdir, "state.json")
        with open(state_path, "r") as f:
            raw_state = json.load(f)
        for rec in raw_state["outbound"].values():
            rec.pop("email_deleted", None)
            rec.pop("attach_ack_received", None)
        with open(state_path, "w") as f:
            json.dump(raw_state, f)
        st3 = StateStore(state_dir=tmpdir)
        old_rec = st3.get_outbound(mid)
        _report("R3.10", old_rec is not None and old_rec.get("email_deleted") is None,
                "[UNIT] Old state files without new fields load correctly")

    finally:
        shutil.rmtree(tmpdir)


# ──────────────────────────────────────────────────────────────
# R4: main.py — handler signatures and import chain
# ──────────────────────────────────────────────────────────────

def test_r4_main_imports():
    _section("R4: main.py import chain and handler signatures")

    # R4.1: main.py imports successfully (cleanup.py exists and is importable)
    try:
        import main
        _report("R4.1", True,
                "[UNIT] main.py imports successfully (cleanup.py dependency resolved)")
    except ImportError as e:
        _report("R4.1", False,
                "[UNIT] main.py imports successfully",
                f"ImportError: {e}")
    except Exception as e:
        _report("R4.1", False,
                "[UNIT] main.py imports successfully",
                f"{type(e).__name__}: {e}")

    # R4.2: Handler functions have correct signatures
    import inspect
    from main import _handle_inbound_ack, _handle_inbound_nack, _handle_inbound_attach_ack

    for name, fn in [("_handle_inbound_ack", _handle_inbound_ack),
                     ("_handle_inbound_nack", _handle_inbound_nack),
                     ("_handle_inbound_attach_ack", _handle_inbound_attach_ack)]:
        sig = inspect.signature(fn)
        params = list(sig.parameters.keys())
        _report(f"R4.2:{name}", params == ["config", "state", "env"],
                f"[UNIT] {name} signature is (config, state, env)",
                f"Got: {params}")

    # R4.3: process_inbound is callable (smoke test — won't actually poll)
    from main import process_inbound
    _report("R4.3", callable(process_inbound),
            "[UNIT] process_inbound is callable")

    # R4.4: _try_cleanup is defined and callable
    from main import _try_cleanup
    _report("R4.4", callable(_try_cleanup),
            "[UNIT] _try_cleanup is defined and callable")

    # R4.5: BackgroundWorker class exists
    from main import BackgroundWorker
    _report("R4.5", hasattr(BackgroundWorker, "run") and hasattr(BackgroundWorker, "stop"),
            "[UNIT] BackgroundWorker has run() and stop() methods")


# ──────────────────────────────────────────────────────────────
# R5: cleanup.py — module health (no live IMAP needed)
# ──────────────────────────────────────────────────────────────

def test_r5_cleanup_module():
    _section("R5: cleanup.py module health")

    # R5.1: Import succeeds
    try:
        from cleanup import delete_sent_email, cleanup_acknowledged, cleanup_expired, _is_cleanup_eligible
        _report("R5.1", True,
                "[UNIT] cleanup.py imports successfully")
    except Exception as e:
        _report("R5.1", False,
                "[UNIT] cleanup.py imports successfully",
                f"{type(e).__name__}: {e}")
        return  # Skip rest if import fails

    from cleanup import _is_cleanup_eligible

    # R5.2: _is_cleanup_eligible — text-only ACKNOWLEDGED
    rec_text_ack = {"state": OUT_ACKNOWLEDGED, "envelope": {"has_attachment": False}}
    _report("R5.2", _is_cleanup_eligible(rec_text_ack) is True,
            "[UNIT] Text-only ACKNOWLEDGED is eligible for cleanup")

    # R5.3: _is_cleanup_eligible — attachment ACKNOWLEDGED but no ATTACH_ACK
    rec_att_ack_only = {"state": OUT_ACKNOWLEDGED, "envelope": {"has_attachment": True}}
    _report("R5.3", _is_cleanup_eligible(rec_att_ack_only) is False,
            "[UNIT] Attachment ACKNOWLEDGED without ATTACH_ACK is NOT eligible")

    # R5.4: _is_cleanup_eligible — attachment with both ACK + ATTACH_ACK
    rec_att_both = {"state": OUT_ACKNOWLEDGED, "envelope": {"has_attachment": True},
                    "attach_ack_received": True}
    _report("R5.4", _is_cleanup_eligible(rec_att_both) is True,
            "[UNIT] Attachment ACKNOWLEDGED + ATTACH_ACK IS eligible")

    # R5.5: _is_cleanup_eligible — NACKED (always eligible)
    rec_nack = {"state": OUT_NACKED, "envelope": {"has_attachment": True}}
    _report("R5.5", _is_cleanup_eligible(rec_nack) is True,
            "[UNIT] NACKED is always eligible for cleanup")

    # R5.6: _is_cleanup_eligible — FAILED (always eligible)
    rec_fail = {"state": OUT_FAILED, "envelope": {"has_attachment": True}}
    _report("R5.6", _is_cleanup_eligible(rec_fail) is True,
            "[UNIT] FAILED is always eligible for cleanup")

    # R5.7: _is_cleanup_eligible — already deleted
    rec_deleted = {"state": OUT_ACKNOWLEDGED, "envelope": {"has_attachment": False},
                   "email_deleted": True}
    _report("R5.7", _is_cleanup_eligible(rec_deleted) is False,
            "[UNIT] Already-deleted record is NOT eligible")

    # R5.8: _is_cleanup_eligible — non-terminal state
    rec_waiting = {"state": OUT_WAITING_FOR_ACK, "envelope": {"has_attachment": False}}
    _report("R5.8", _is_cleanup_eligible(rec_waiting) is False,
            "[UNIT] WAITING_FOR_ACK is NOT eligible")

    # R5.9: cleanup_expired with max_days=0 does nothing
    tmpdir = tempfile.mkdtemp()
    try:
        st = StateStore(state_dir=tmpdir)
        env = build_envelope(MSG_DATA, "s", "r", payload="test")
        st.record_outbound(env["message_id"], env, OUT_WAITING_FOR_ACK)
        # Backdate the record
        st.data["outbound"][env["message_id"]]["created_at"] = \
            (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        st._save()

        cfg = {"email_max_lifetime_days": 0, "endpoint_id": "s",
               "email_address": "x", "email_password": "x",
               "imap_host": "x", "imap_port": 993}
        count = cleanup_expired(cfg, st)
        _report("R5.9", count == 0,
                "[UNIT] cleanup_expired with max_days=0 returns 0 (disabled)")
    finally:
        shutil.rmtree(tmpdir)


# ──────────────────────────────────────────────────────────────
# R6: transport.py — fetch_protocol_emails logic (LIVE)
# ──────────────────────────────────────────────────────────────

def test_r6_transport_live(config: dict):
    _section("R6: transport.py — live IMAP/SMTP tests")

    from transport import send_email, fetch_protocol_emails

    # R6.0: Drain any leftover BEIS emails from previous test runs
    #       so they don't interfere with our targeted test.
    print("       🧹 Draining leftover BEIS emails from mailbox...")
    drained = fetch_protocol_emails(config)
    if drained:
        print(f"       Drained {len(drained)} old emails")
    time.sleep(2)

    # R6.1: send_email still works
    env = build_envelope(MSG_DATA, config["endpoint_id"], config["peers"][0],
                         payload=f"REGRESSION-TEST-{int(time.time())}")
    mid = env["message_id"]
    success = send_email(config, env)
    _report("R6.1", success,
            "[LIVE] send_email succeeds")

    if not success:
        _skip("R6.2", "[LIVE] fetch_protocol_emails picks up the message", "send failed")
        _skip("R6.3", "[LIVE] Consumed messages are removed from mailbox", "send failed")
        return

    # R6.2: fetch_protocol_emails picks up a self-addressed test message.
    #       Send a message TO ourselves (from a peer's perspective) so fetch picks it up.
    #       Gmail self-to-self delivery can be slow, so we poll with retries.
    env_self = build_envelope(MSG_DATA, config["peers"][0], config["endpoint_id"],
                              payload=f"REGRESSION-SELF-{int(time.time())}")
    mid_self = env_self["message_id"]
    send_email(config, env_self)

    found = False
    all_fetched: list[dict] = []
    for attempt in range(4):
        wait = 10 if attempt == 0 else 8
        print(f"       ⏳ Waiting {wait}s for Gmail delivery (attempt {attempt + 1}/4)...")
        time.sleep(wait)
        fetched = fetch_protocol_emails(config)
        all_fetched.extend(fetched)
        found = any(e["message_id"] == mid_self for e in fetched)
        if found:
            break

    _report("R6.2", found,
            "[LIVE] fetch_protocol_emails picks up self-addressed message",
            f"Found after {attempt + 1} attempts, total fetched={len(all_fetched)}, looking for {mid_self[:8]}…")

    # R6.3: The specific consumed message should NOT appear on a second fetch.
    #        (Other messages may appear due to async Gmail delivery — that's fine.)
    if found:
        time.sleep(3)
        fetched2 = fetch_protocol_emails(config)
        still_there = any(e["message_id"] == mid_self for e in fetched2)
        _report("R6.3", not still_there,
                "[LIVE] Consumed message not returned on second fetch",
                f"Second fetch returned {len(fetched2)} envelopes (other messages OK)")
    else:
        _skip("R6.3", "[LIVE] Consumed message not returned on second fetch", "message not found in R6.2")


# ──────────────────────────────────────────────────────────────
# R7: Full round-trip — text message send → ACK (LIVE)
# ──────────────────────────────────────────────────────────────

def test_r7_text_roundtrip(config: dict, state: StateStore):
    _section("R7: Full text message round-trip (LIVE)")

    from main import process_inbound
    from transport import send_email

    peer = config["peers"][0] if config["peers"] else None
    if not peer:
        _skip("R7.1", "[LIVE] Text round-trip", "no peers configured")
        return

    # R7.1: Send a DATA message
    env = build_envelope(MSG_DATA, config["endpoint_id"], peer,
                         payload=f"REGRESSION-R7-{int(time.time())}")
    mid = env["message_id"]
    state.record_outbound(mid, env, OUT_CREATED)
    success = send_email(config, env)
    state.update_outbound_state(mid, OUT_WAITING_FOR_ACK if success else OUT_FAILED)
    _report("R7.1", success,
            "[LIVE] DATA message sent successfully",
            f"msg_id={mid[:8]}…  to={peer}")

    if not success:
        _skip("R7.2", "[LIVE] Outbound state is WAITING_FOR_ACK", "send failed")
        return

    # R7.2: State should be WAITING_FOR_ACK
    rec = state.get_outbound(mid)
    _report("R7.2", rec is not None and rec["state"] == OUT_WAITING_FOR_ACK,
            "[LIVE] Outbound state is WAITING_FOR_ACK")


# ──────────────────────────────────────────────────────────────
# R8: State store interaction — no data corruption after new fields
# ──────────────────────────────────────────────────────────────

def test_r8_state_integrity():
    _section("R8: State store data integrity with new fields")

    tmpdir = tempfile.mkdtemp()
    try:
        st = StateStore(state_dir=tmpdir)

        # Create several records, mix of old-style and new-style
        envs = []
        for i in range(5):
            env = build_envelope(MSG_DATA, f"sender-{i}", f"recipient-{i}",
                                 payload=f"test-{i}",
                                 has_attachment=(i % 2 == 0))
            envs.append(env)
            st.record_outbound(env["message_id"], env, OUT_CREATED)

        # Transition some to various states
        st.update_outbound_state(envs[0]["message_id"], OUT_ACKNOWLEDGED)
        st.mark_email_deleted(envs[0]["message_id"], True)

        st.update_outbound_state(envs[1]["message_id"], OUT_NACKED)

        st.update_outbound_state(envs[2]["message_id"], OUT_WAITING_FOR_ACK)
        st.increment_retry(envs[2]["message_id"])

        st.update_outbound_state(envs[3]["message_id"], OUT_FAILED)

        # envs[4] stays CREATED

        # R8.1: All records intact
        all_found = all(st.get_outbound(e["message_id"]) is not None for e in envs)
        _report("R8.1", all_found,
                "[UNIT] All 5 outbound records exist after mixed operations")

        # R8.2: States are correct
        states = [st.get_outbound(e["message_id"])["state"] for e in envs]
        expected = [OUT_ACKNOWLEDGED, OUT_NACKED, OUT_WAITING_FOR_ACK, OUT_FAILED, OUT_CREATED]
        _report("R8.2", states == expected,
                "[UNIT] All state values are correct after transitions",
                f"Got: {states}")

        # R8.3: get_outbound_by_state still works for each state
        for exp_state in [OUT_ACKNOWLEDGED, OUT_NACKED, OUT_WAITING_FOR_ACK, OUT_FAILED, OUT_CREATED]:
            matches = st.get_outbound_by_state(exp_state)
            count = len(matches)
            if count != 1:
                _report(f"R8.3:{exp_state}", False,
                        f"[UNIT] get_outbound_by_state({exp_state}) returns 1 record",
                        f"Got {count}")
                break
        else:
            _report("R8.3", True,
                    "[UNIT] get_outbound_by_state returns correct count for all states")

        # R8.4: Reload from disk preserves everything
        st2 = StateStore(state_dir=tmpdir)
        states2 = [st2.get_outbound(e["message_id"])["state"] for e in envs]
        _report("R8.4", states2 == expected,
                "[UNIT] States survive full reload from disk")

        deleted_flag = st2.get_outbound(envs[0]["message_id"]).get("email_deleted")
        _report("R8.5", deleted_flag is True,
                "[UNIT] email_deleted flag survives reload")

    finally:
        shutil.rmtree(tmpdir)


# ──────────────────────────────────────────────────────────────
# Summary
# ──────────────────────────────────────────────────────────────

def print_summary():
    print(f"\n{'═' * 60}")
    print(f"  REGRESSION TEST SUMMARY")
    print(f"{'═' * 60}")
    total = PASS + FAIL + SKIP
    print(f"  Total: {total}  |  ✅ Pass: {PASS}  |  ❌ Fail: {FAIL}  |  ⏭️  Skip: {SKIP}")
    print(f"{'═' * 60}")
    if FAIL > 0:
        print("\n  FAILURES:")
        for tid, status, desc in RESULTS:
            if status == "FAIL":
                print(f"    ❌ {tid}: {desc}")
    print()
    return FAIL == 0


# ──────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────

def main():
    # Suppress logging noise during tests
    logging.getLogger("app").setLevel(logging.CRITICAL)
    logging.getLogger("comm").setLevel(logging.CRITICAL)

    print("=" * 60)
    print("  BEIS MVP — Regression Test Suite")
    print("=" * 60)

    # ── UNIT TESTS (no credentials needed) ──
    test_r1_config()
    test_r2_envelope()
    test_r3_state_store()
    test_r4_main_imports()
    test_r5_cleanup_module()
    test_r8_state_integrity()

    # ── LIVE TESTS (need config.json with real credentials) ──
    live = "--live" in sys.argv
    if live:
        config_path = "config.json"
        for i, arg in enumerate(sys.argv):
            if arg == "-c" and i + 1 < len(sys.argv):
                config_path = sys.argv[i + 1]

        if os.path.exists(config_path):
            config = load_config(config_path)
            state = StateStore()
            test_r6_transport_live(config)
            test_r7_text_roundtrip(config, state)
        else:
            _skip("R6.*", "[LIVE] transport tests", f"No {config_path} found")
            _skip("R7.*", "[LIVE] round-trip tests", f"No {config_path} found")
    else:
        print(f"\n{'─' * 60}")
        print("  LIVE tests skipped (run with --live to include)")
        print(f"{'─' * 60}")

    all_passed = print_summary()
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
