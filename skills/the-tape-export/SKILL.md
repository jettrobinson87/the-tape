---
name: the-tape-export
description: "Export OpenClaw session history into a shareable .tape.json (The Tape v1) replay file"
metadata:
  openclaw:
    emoji: "📼"
---

# 📼 the-tape-export

Use this skill when the user asks for a **Tape** (a shareable replay) of an OpenClaw session.

## Goal

Convert an OpenClaw session into a `*.tape.json` file (The Tape v1 format), with **best-effort redaction**, and save it under:

`./tapes/<date>-<slug>.tape.json`

## Procedure

1) **List sessions**
- Call `sessions_list` to find the relevant session key (usually the most recent).

2) **Fetch full history**
- Call `sessions_history` for that key.
- Include tool results (the point is to replay *actions* and *outputs*).

3) **Build Tape steps**
- Map messages to step types:
  - user text → `user`
  - assistant thinking → `thought`
  - assistant tool calls → `action`
  - tool results → attach to the prior `action` step when possible; otherwise create `result`/`error`
  - assistant text → `result`

4) **Redact**
- Before writing the tape file, redact:
  - obvious API keys/tokens
  - email addresses
  - phone numbers
- Prefer over-redaction to leaking secrets.

5) **Write**
- Write a The Tape v1 JSON file.

## Output format (minimal)

- Top-level: `$schema`, `version`, `metadata`, `summary`, `steps[]`
- Each step: `id`, `type`, `elapsed_seconds`, `content`

> If you don’t have exact timestamps, approximate `elapsed_seconds` by step index (still replayable).
