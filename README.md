# 📼 The Tape

**"Link the Tape or it didn't happen."**

The Tape is a replay player for AI agent runs — think **Twitch/TikTok for agent execution**. Instead of "trust me bro," you share a **playable timeline** of what the agent actually did.

## Quick Start

```bash
# 1. Clone / download this repo
# 2. Serve it locally (required for full functionality)
python -m http.server 8000

# 3. Open http://localhost:8000 in your browser
# 4. Drag in a .tape.json or OpenClaw .jsonl file
```

## Features

- **Multi-format support**: Tape v1 JSON, legacy formats, OpenClaw `.jsonl` transcripts
- **Auto-redaction**: API keys, tokens, emails, phones, IPs, JWTs, private keys (viewing toggle)
- **Note:** The redaction toggle only affects what you see on-screen. **Copy Link** and **Publish** always export a redacted tape.
- **Shareable links**: Small tapes embed in URL hash; larger tapes download as files
- **XSS-safe**: All user content is HTML-escaped before rendering
- **Keyboard shortcuts**: Full playback control without touching the mouse

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `Space` | Play/Pause |
| `←` | Previous step |
| `→` | Next step |
| `↑` | Jump to start |
| `↓` | Jump to end |
| `R` | Toggle redaction |
| `1-4` | Playback speed (0.5x, 1x, 2x, 4x) |

## Formats Supported

### 1. The Tape v1 (`*.tape.json`)

Structured JSON with `metadata` + `steps[]`. This is the canonical shareable format.

```json
{
  "$schema": "https://the-tape.ai/schemas/tape.schema.json",
  "version": "1.0",
  "metadata": { "title": "...", "duration_seconds": 47 },
  "steps": [
    { "id": "step_1", "type": "thought", "elapsed_seconds": 0, "content": { "text": "..." } }
  ]
}
```

### 2. OpenClaw Session Transcripts (`*.jsonl`)

The player converts OpenClaw session logs on the fly. Just drag in your `.jsonl` file.

## Auto-Export Hook (Recommended)

Want tapes created automatically when you `/stop`?

### Install the hook

```bash
# Copy to your workspace
cp -r hooks/tape-export <workspace>/hooks/

# Or install globally
cp -r hooks/tape-export ~/.openclaw/hooks/
openclaw hooks enable tape-export
```

### What it does

1. Listens for `command:stop`
2. Reads the session transcript
3. Converts to Tape v1 format with redaction
4. Writes `tapes/<date>-<slug>.tape.json` to your workspace

## Manual Conversion

```bash
python scripts/openclaw_session_to_tape.py \
  --in ~/.openclaw/sessions/<session>.jsonl \
  --out my-tape.tape.json
```

Disable redaction (not recommended):
```bash
python scripts/openclaw_session_to_tape.py --in session.jsonl --out tape.json --no-redact
```

## Sharing

- **Copy Link**: Creates a URL with the tape embedded in the hash (small tapes only)
- **Publish**: Downloads a redacted `.tape.json` file you can host anywhere

⚠️ **Always review tapes before sharing.** Redaction is best-effort, not bulletproof.

## Redaction Patterns

The player and export tools redact:

| Pattern | Example |
|---------|---------|
| OpenAI keys | `sk-...` |
| Anthropic keys | `sk-ant-...` |
| GitHub tokens | `ghp_...`, `gho_...` |
| AWS keys | `AKIA...` |
| Slack tokens | `xoxb-...` |
| Bearer tokens | `Bearer eyJ...` |
| JWTs | `eyJ...` (three-part base64) |
| Private keys | `-----BEGIN PRIVATE KEY-----` |
| DB connections | `postgres://...` |
| Emails | `user@example.com` |
| Phone numbers | `+1 (555) 123-4567` |
| IP addresses | `192.168.1.1` |

## Project Structure

```
the-tape/
├── index.html              # The player (single-file web app)
├── README.md               # You are here
├── examples/
│   ├── flappy-bird-speedrun.tape.json
│   └── openclaw-session.example.jsonl
├── hooks/
│   └── tape-export/
│       ├── HOOK.md         # OpenClaw hook manifest
│       └── handler.ts      # Export logic
├── scripts/
│   └── openclaw_session_to_tape.py
└── skills/
    └── the-tape-export/
        └── SKILL.md
```

## Why This Exists

Right now, an agent is a black box. It thinks for 30 seconds and says "Done." You have no idea if it:

- Hallucinated half the steps
- Checked the wrong price
- Leaked your API key
- Actually wrote good code

**The Tape makes the invisible visible.**

When someone claims their agent did something impressive, the response should be:

> "Link the Tape or it didn't happen."

## Roadmap

- [ ] Hosted tape URLs (permanent shareable links)
- [ ] Verified Tape signatures (prove authenticity)
- [ ] Public/Debug export presets
- [ ] Multi-run "channel" pages (feed of tapes)
- [ ] Embeddable player widget
- [ ] Team workspaces + private libraries

## License

MIT
