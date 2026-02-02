---
name: tape-export
description: "Export the current session transcript into a shareable .tape.json when you issue /stop"
metadata: {"openclaw": {"emoji": "📼", "events": ["command:stop"], "requires": {"bins": ["node"]}}}
---

# 📼 tape-export

This hook listens for `command:stop` and exports the active session transcript into a **The Tape v1** `*.tape.json` file.

## Installation

**Option 1: Workspace hook (per-agent)**
```bash
# Copy to your workspace
cp -r hooks/tape-export <your-workspace>/hooks/
```

**Option 2: Global hook**
```bash
# Copy to global hooks directory
cp -r hooks/tape-export ~/.openclaw/hooks/

# Enable the hook
openclaw hooks enable tape-export
```

## What it does

1. Listens for `command:stop` events
2. Reads `sessionFile` path from hook context
3. Converts OpenClaw JSONL transcript → The Tape v1 format
4. Applies best-effort secret redaction
5. Writes `tapes/<date>-<slug>.tape.json` in your workspace

## Output location

Tapes are written to:
```
<workspace>/tapes/<date>-<slug>.tape.json
```

Example: `tapes/2026-02-01-fix-the-login-bug.tape.json`

## Redaction

The export applies automatic redaction for:
- API keys (OpenAI, Anthropic, GitHub, AWS, Slack, Google)
- Bearer tokens and JWTs
- Email addresses
- Phone numbers
- IP addresses
- Private keys
- Database connection strings

⚠️ **Always review tapes before sharing publicly.** Redaction is best-effort, not bulletproof.

## Manual conversion

You can also convert transcripts manually:
```bash
python scripts/openclaw_session_to_tape.py \
  --in ~/.openclaw/sessions/<session>.jsonl \
  --out my-tape.tape.json
```
