# MVP Devlog — Agent Build Instructions

DO NOT SUMMARIZE. DO NOT SKIP PHASES. Complete each phase fully before moving to the next.

---

## PHASE 1 — Read all source files RAW

Read every file listed below in full. Do not interpret. Do not summarize. Just confirm each file was read.

Files to read:
- `MVP/main.py`
- `MVP/envelope.py`
- `MVP/transport.py`
- `MVP/state_store.py`
- `MVP/config_loader.py`
- `MVP/config.json`

Confirm each file was read by printing its filename and line count only.

---

## PHASE 2 — Read all test instance files RAW

Read every file listed below in full. Do not interpret. Do not summarize.

Files to read:
- `MVP/test1/config.json`
- `MVP/test1/state.json` (if exists)
- `MVP/test1/app.log` (full content)
- `MVP/test1/communication.log` (full content)
- `MVP/test2/config.json`
- `MVP/test2/state.json` (if exists)
- `MVP/test2/app.log` (full content)
- `MVP/test2/communication.log` (full content)

Confirm each file was read by printing its filename and line count only.

---

## PHASE 3 — Read all instruction and spec files RAW

Read every file listed below in full. Do not interpret. Do not summarize.

Files to read:
- `MVP/mvp_instructions.md`
- `Bidirectional Email Interface Specificat.md`
- `MVP/README.md` (if exists)

Confirm each file was read by printing its filename and line count only.

---

## PHASE 4 — Extract raw facts only, NO interpretation

From the files read in Phases 1–3, extract the following raw facts. Do not interpret. Do not add conclusions. Just list the facts.

### 4a — List every module created, with its filename and purpose (one sentence max per module)
### 4b — List every CLI command implemented, exactly as it appears in the code
### 4c — List every message type defined in `envelope.py`, exactly as named in code
### 4d — List every state constant defined in `state_store.py`, exactly as named in code
### 4e — List every log line from `test1/app.log` that contains the word ERROR or WARNING
### 4f — List every log line from `test2/app.log` that contains the word ERROR or WARNING
### 4g — List every entry in `test1/communication.log` verbatim
### 4h — List every entry in `test2/communication.log` verbatim
### 4i — List the final state of every message in `test1/state.json` verbatim
### 4j — List the final state of every message in `test2/state.json` verbatim

---

## PHASE 5 — Extract failures and fixes only, NO interpretation

From the files read in Phases 1–3, extract the following. Do not add conclusions.

### 5a — List every Python exception or traceback found in any log file verbatim
### 5b — List every code change that was made to fix a bug, with the exact before/after code
### 5c — List every place where a `# fix:` or `# bug:` comment appears in source code
### 5d — List the `from __future__ import annotations` issue: what caused it, what file, what line
### 5e — List the `_attachment_data` serialization bug: what the symptom was, what the fix was

---

## PHASE 6 — Write the devlog file

Only after Phases 1–5 are complete, write `MVP/MVP_devlog.md` with the following sections in order:

### Section 1 — Project Overview
- What BEIS MVP is
- What it implements from the spec
- What is explicitly OUT of scope for the MVP

### Section 2 — Module Inventory
- One row per module: filename, purpose, key functions
- Use a table

### Section 3 — Chronological Build Log
- One entry per feature/fix in the order it was built
- Each entry must include: what was built, what files changed, what the expected behaviour was

### Section 4 — Test Results
- One entry per test run documented in the logs
- Each entry must include: test instance, command used, expected result, actual result, PASS/FAIL

### Section 5 — Failures and Fixes
- One entry per bug/failure
- Each entry must include:
  - Bug ID (BUG-001, BUG-002, etc.)
  - Symptom (what was observed)
  - Root cause (exact code/line)
  - Fix applied (exact before/after code)
  - Verified by (what test confirmed the fix)

### Section 6 — Final State
- Final message states from test1/state.json and test2/state.json
- Final directory structure of test1/ and test2/
- List of files in test1/in/ and test2/in/ if they exist

### Section 7 — Known Limitations
- What the MVP does NOT do that the spec requires
- What edge cases are not handled

---

## PHASE GATE RULES

- Do not start Phase N+1 until Phase N output is confirmed complete
- Do not summarize log files — quote them verbatim where required
- Do not invent test results — only document what the logs prove happened
- If a file does not exist, state "FILE NOT FOUND" — do not skip the step