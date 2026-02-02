#!/usr/bin/env python3

"""
openclaw_session_to_tape.py

Convert an OpenClaw session transcript (*.jsonl) into a shareable The Tape v1 (*.tape.json).

Usage:
  python scripts/openclaw_session_to_tape.py --in path/to/session.jsonl --out path/to/out.tape.json

Notes:
- This script does best-effort parsing; transcript schemas can evolve.
- Redaction is ON by default; disable with --no-redact (not recommended).
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


REDACTION_RULES: List[Tuple[re.Pattern, str]] = [
    # API keys
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "sk-REDACTED"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9\-]{20,}\b"), "sk-ant-REDACTED"),
    (re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"), "AIzaREDACTED"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), "gh_REDACTED"),
    (re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{10,}\b"), "xox-REDACTED"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9\-\._~\+/]+=*\b"), "Bearer REDACTED"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AKIAREDACTED"),
    (re.compile(r"\b[A-Za-z0-9/+=]{40}\b"), "[aws-secret-redacted]"),
    # Private keys (PEM blocks) - single rule to catch whole block
    (re.compile(r"-----BEGIN [A-Z0-9 ]+-----[\s\S]*?-----END [A-Z0-9 ]+-----"), "[pem-block-redacted]"),
    # JWTs
    (re.compile(r"\beyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\b"), "[jwt-redacted]"),
    # Database connection strings
    (re.compile(r"(postgres|mysql|mongodb|redis)://[^\s\"']+", re.IGNORECASE), "[db-connection-redacted]"),
    # PII
    (re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE), "[email-redacted]"),
    (re.compile(r"\b(\+?\d[\d\s().-]{7,}\d)\b"), "[phone-redacted]"),
    (re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"), "[ip-redacted]"),
]


def redact(text: str, enabled: bool) -> str:
    if not enabled:
        return text
    out = text or ""
    for pat, rep in REDACTION_RULES:
        out = pat.sub(rep, out)
    return out


def safe_json(value: Any, max_len: int = 6000) -> str:
    if value is None:
        return ""
    try:
        if isinstance(value, str):
            s = value
        else:
            s = json.dumps(value, indent=2, ensure_ascii=False)
    except Exception:
        s = str(value)
    if len(s) > max_len:
        s = s[:max_len] + "\n…(truncated)…"
    return s


def parse_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def parse_ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


def slugify(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    s = re.sub(r"(^-+)|(-+$)", "", s)
    return (s[:48] or "tape")


def normalize_openclaw(records: List[Dict[str, Any]], filename_hint: str) -> Dict[str, Any]:
    session_meta = next((r for r in records if r.get("type") == "session"), None)
    message_recs = [r for r in records if r.get("type") == "message" or r.get("message")]

    if not message_recs:
        raise ValueError("No message records found in JSONL.")

    start_dt = parse_ts(message_recs[0].get("timestamp")) or (parse_ts(session_meta.get("timestamp")) if session_meta else None) or datetime.utcnow()

    steps: List[Dict[str, Any]] = []
    tool_stack: List[int] = []

    for rec in message_recs:
        msg = rec.get("message") or rec
        role = msg.get("role") or rec.get("role") or "assistant"
        ts = parse_ts(rec.get("timestamp")) or start_dt
        t = max(0.0, (ts - start_dt).total_seconds())

        content = msg.get("content")
        if not isinstance(content, list):
            content = rec.get("content")
        if not isinstance(content, list):
            content = []

        if role == "user":
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text" and c.get("text"):
                    steps.append({"type": "user", "t": t, "text": str(c["text"]), "code": ""})
            continue

        if role == "assistant":
            for c in content:
                if not isinstance(c, dict):
                    continue
                ctype = c.get("type")
                if ctype == "thinking" and (c.get("text") or c.get("thinking")):
                    steps.append({"type": "thought", "t": t, "text": str(c.get("text") or c.get("thinking")), "code": ""})
                elif ctype == "text" and c.get("text"):
                    steps.append({"type": "result", "t": t, "text": str(c["text"]), "code": ""})
                elif ctype == "toolCall":
                    tool_name = str(c.get("name") or c.get("tool") or "tool")
                    args = c.get("args") if "args" in c else c.get("arguments")
                    if args is None:
                        args = c.get("params") if "params" in c else c.get("input")
                    code = safe_json(args, 6000) if args is not None else ""
                    idx = len(steps)
                    steps.append({"type": "action", "t": t, "text": tool_name, "code": code, "tool": tool_name})
                    tool_stack.append(idx)
            continue

        if role == "toolResult":
            parts: List[str] = []
            if content:
                for c in content:
                    if isinstance(c, dict) and c.get("type") == "text" and c.get("text"):
                        parts.append(str(c["text"]))
                    else:
                        parts.append(safe_json(c, 2000))
            else:
                parts.append(safe_json(msg, 4000))
            payload = "\n\n".join([p for p in parts if p])

            is_err = bool(msg.get("error") or msg.get("isError")) or bool(re.search(r"error|exception|traceback", payload, re.IGNORECASE))

            if tool_stack:
                idx = tool_stack.pop()
                if 0 <= idx < len(steps) and steps[idx].get("type") == "action":
                    combined: List[str] = []
                    if steps[idx].get("code"):
                        combined.append(f"call:\n{steps[idx]['code']}")
                    combined.append(("error:\n" if is_err else "result:\n") + payload)
                    steps[idx]["code"] = "\n\n".join(combined)
                    if is_err:
                        steps.append({"type": "error", "t": t, "text": "Tool error", "code": payload})
                    continue

            steps.append({"type": "error" if is_err else "result", "t": t, "text": "Tool error" if is_err else "Tool result", "code": payload})
            continue

    title = filename_hint
    first_user = next((s for s in steps if s.get("type") == "user" and s.get("text")), None)
    if first_user:
        t = str(first_user["text"]).strip()
        title = (t[:64] + "…") if len(t) > 64 else t
    elif session_meta:
        title = str(session_meta.get("sessionKey") or session_meta.get("key") or title)

    duration = max([float(s.get("t") or 0.0) for s in steps], default=0.0)
    recorded_at = (session_meta.get("timestamp") if session_meta else None) or datetime.utcnow().isoformat() + "Z"

    return {"title": title, "recorded_at": recorded_at, "duration_seconds": duration, "steps": steps}


def build_tape_v1(normalized: Dict[str, Any], redact_enabled: bool) -> Dict[str, Any]:
    steps_out: List[Dict[str, Any]] = []
    tools_used = sorted({str(s.get("tool")) for s in normalized["steps"] if s.get("type") == "action" and s.get("tool")})

    for i, s in enumerate(normalized["steps"]):
        stype = str(s.get("type") or "result")
        t = float(s.get("t") or 0.0)
        text = redact(str(s.get("text") or ""), redact_enabled)
        code = redact(str(s.get("code") or ""), redact_enabled)
        tool = redact(str(s.get("tool") or ""), redact_enabled) if s.get("tool") else None

        content: Dict[str, Any] = {}
        if stype in ("thought", "user"):
            content["text"] = text
        elif stype == "action":
            content["tool"] = tool or "tool"
            content["description"] = text
            if code:
                content["output"] = code
        elif stype == "error":
            content["message"] = text or "Error"
            if code:
                content["stack_preview"] = code
        else:
            content["description"] = text or "Result"
            if code:
                content["details"] = code

        steps_out.append(
            {
                "id": f"step_{i+1}",
                "type": stype,
                "timestamp": None,
                "elapsed_seconds": t,
                "content": content,
            }
        )

    errors = sum(1 for s in steps_out if s["type"] == "error")

    return {
        "$schema": "https://the-tape.ai/schemas/tape.schema.json",
        "version": "1.0",
        "metadata": {
            "title": redact(str(normalized["title"]), redact_enabled),
            "recorded_at": normalized["recorded_at"],
            "duration_seconds": normalized["duration_seconds"],
            "agent": {"name": "OpenClaw Agent", "version": "unknown"},
            "tags": ["exported"],
        },
        "summary": {"steps": len(steps_out), "tools_used": tools_used, "errors": errors},
        "steps": steps_out,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="Input OpenClaw session transcript (.jsonl)")
    ap.add_argument("--out", dest="out", default=None, help="Output .tape.json path")
    ap.add_argument("--no-redact", action="store_true", help="Disable redaction (NOT recommended)")
    args = ap.parse_args()

    inp = args.inp
    if not os.path.exists(inp):
        raise SystemExit(f"Input not found: {inp}")

    out = args.out
    if out is None:
        base = os.path.splitext(os.path.basename(inp))[0]
        out = base + ".tape.json"

    records = parse_jsonl(inp)
    normalized = normalize_openclaw(records, os.path.basename(inp))
    tape = build_tape_v1(normalized, redact_enabled=(not args.no_redact))

    with open(out, "w", encoding="utf-8") as f:
        json.dump(tape, f, indent=2, ensure_ascii=False)

    print(f"Wrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
