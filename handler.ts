import fs from "node:fs/promises";
import path from "node:path";

const REDACTION_RULES: Array<{ re: RegExp; rep: string }> = [
  // API keys
  { re: /\bsk-[A-Za-z0-9]{20,}\b/g, rep: "sk-REDACTED" },
  { re: /\bsk-ant-[A-Za-z0-9\-]{20,}\b/g, rep: "sk-ant-REDACTED" },
  { re: /\bAIza[0-9A-Za-z\-_]{35}\b/g, rep: "AIzaREDACTED" },
  { re: /\bgh[pousr]_[A-Za-z0-9]{20,}\b/g, rep: "gh_REDACTED" },
  { re: /\bxox[baprs]-[0-9A-Za-z-]{10,}\b/g, rep: "xox-REDACTED" },
  { re: /\bBearer\s+[A-Za-z0-9\-\._~\+/]+=*\b/g, rep: "Bearer REDACTED" },
  { re: /\bAKIA[0-9A-Z]{16}\b/g, rep: "AKIAREDACTED" },
  { re: /\b[A-Za-z0-9/+=]{40}\b/g, rep: "[aws-secret-redacted]" },
  // Private keys (PEM blocks) - single rule to catch whole block
  { re: /-----BEGIN [A-Z0-9 ]+-----[\s\S]*?-----END [A-Z0-9 ]+-----/g, rep: "[pem-block-redacted]" },
  // JWTs
  { re: /\beyJ[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]*\.[A-Za-z0-9_-]+\b/g, rep: "[jwt-redacted]" },
  // Database connection strings
  { re: /(postgres|mysql|mongodb|redis):\/\/[^\s"']+/gi, rep: "[db-connection-redacted]" },
  // PII
  { re: /\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi, rep: "[email-redacted]" },
  { re: /\b(\+?\d[\d\s().-]{7,}\d)\b/g, rep: "[phone-redacted]" },
  { re: /\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b/g, rep: "[ip-redacted]" },
];

function redact(str: string): string {
  let out = String(str ?? "");
  for (const rule of REDACTION_RULES) out = out.replace(rule.re, rule.rep);
  return out;
}

function safeJson(value: any, maxLen = 6000): string {
  if (value == null) return "";
  let s = "";
  try {
    if (typeof value === "string") s = value;
    else s = JSON.stringify(value, null, 2);
  } catch {
    s = String(value);
  }
  if (s.length > maxLen) return s.slice(0, maxLen) + "\n…(truncated)…";
  return s;
}

function slugify(s: string): string {
  return String(s || "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 48) || "tape";
}

function parseJsonl(text: string): any[] {
  const lines = text.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
  const out: any[] = [];
  for (const line of lines) {
    try { out.push(JSON.parse(line)); }
    catch { /* skip */ }
  }
  return out;
}

function pickFirstUserTitle(steps: any[]): string | null {
  const u = steps.find(s => s.type === "user" && typeof s.text === "string" && s.text.trim());
  if (!u) return null;
  const t = u.text.trim();
  return t.length > 64 ? t.slice(0, 64) + "…" : t;
}

function normalizeOpenClawJsonl(records: any[], filenameHint: string) {
  const sessionMeta = records.find(r => r && r.type === "session") || null;
  const messageRecords = records.filter(r => r && (r.type === "message" || r.message));
  if (!messageRecords.length) throw new Error("No message records found.");

  const parseTs = (v: any): Date | null => {
    if (!v) return null;
    const d = new Date(v);
    return Number.isFinite(d.getTime()) ? d : null;
  };

  let startDate = parseTs(messageRecords[0].timestamp) || parseTs(sessionMeta && sessionMeta.timestamp) || new Date();

  const steps: any[] = [];
  const toolStack: number[] = [];

  for (const rec of messageRecords) {
    const role = rec.message?.role || rec.role || "assistant";
    const ts = parseTs(rec.timestamp) || startDate;
    const t = (ts.getTime() - startDate.getTime()) / 1000;
    const contentArr = Array.isArray(rec.message?.content) ? rec.message.content : (Array.isArray(rec.content) ? rec.content : []);

    if (role === "user") {
      for (const c of contentArr) {
        if (c && c.type === "text" && c.text) {
          steps.push({ type: "user", t, text: String(c.text), code: "" });
        }
      }
      continue;
    }

    if (role === "assistant") {
      for (const c of contentArr) {
        if (!c || !c.type) continue;
        if (c.type === "thinking" && (c.text || c.thinking)) {
          steps.push({ type: "thought", t, text: String(c.text || c.thinking), code: "" });
        } else if (c.type === "text" && c.text) {
          steps.push({ type: "result", t, text: String(c.text), code: "" });
        } else if (c.type === "toolCall") {
          const toolName = String(c.name || c.tool || "tool");
          const args = c.args ?? c.arguments ?? c.params ?? c.input ?? null;
          const code = args == null ? "" : safeJson(args, 6000);
          const idx = steps.length;
          steps.push({ type: "action", t, text: toolName, code, tool: toolName });
          toolStack.push(idx);
        }
      }
      continue;
    }

    if (role === "toolResult") {
      let payloadText = "";
      if (contentArr.length) {
        payloadText = contentArr.map((c: any) => {
          if (c && c.type === "text" && c.text) return String(c.text);
          return safeJson(c, 2000);
        }).join("\n\n");
      } else {
        payloadText = safeJson(rec.message || rec, 4000);
      }
      const isErr = /error|exception|traceback/i.test(payloadText) || Boolean(rec.message?.error || rec.message?.isError);
      if (toolStack.length) {
        const idx = toolStack.pop()!;
        const actionStep = steps[idx];
        if (actionStep && actionStep.type === "action") {
          const combined: string[] = [];
          if (actionStep.code) combined.push(`call:\n${actionStep.code}`);
          combined.push(isErr ? `error:\n${payloadText}` : `result:\n${payloadText}`);
          actionStep.code = combined.join("\n\n");
          if (isErr) steps.push({ type: "error", t, text: "Tool error", code: payloadText });
          continue;
        }
      }
      steps.push({ type: isErr ? "error" : "result", t, text: isErr ? "Tool error" : "Tool result", code: payloadText });
    }
  }

  const title = pickFirstUserTitle(steps) || filenameHint || (sessionMeta && (sessionMeta.sessionKey || sessionMeta.key)) || "OpenClaw Session";
  const durationSeconds = steps.length ? Math.max(...steps.map(s => Number(s.t) || 0)) : 0;

  return {
    title,
    recordedAt: (sessionMeta && sessionMeta.timestamp) ? sessionMeta.timestamp : new Date().toISOString(),
    durationSeconds,
    steps,
  };
}

function buildTapeV1(normalized: any) {
  const tools = Array.from(new Set(normalized.steps.filter((s: any) => s.type === "action" && s.tool).map((s: any) => s.tool))).sort();
  const errors = normalized.steps.filter((s: any) => s.type === "error").length;

  const steps = normalized.steps.map((s: any, i: number) => {
    const t = Number(s.t) || 0;
    const type = String(s.type || "result");
    const text = redact(String(s.text || ""));
    const code = redact(String(s.code || ""));
    const tool = s.tool ? redact(String(s.tool)) : null;

    let content: any = {};
    if (type === "thought" || type === "user") content.text = text;
    else if (type === "action") {
      content.tool = tool || "tool";
      content.description = text;
      if (code) content.output = code;
    } else if (type === "error") {
      content.message = text || "Error";
      if (code) content.stack_preview = code;
    } else {
      content.description = text || "Result";
      if (code) content.details = code;
    }

    return {
      id: `step_${i + 1}`,
      type,
      timestamp: null,
      elapsed_seconds: t,
      content,
    };
  });

  return {
    "$schema": "https://the-tape.ai/schemas/tape.schema.json",
    "version": "1.0",
    "metadata": {
      "title": redact(String(normalized.title || "Tape")),
      "recorded_at": normalized.recordedAt,
      "duration_seconds": normalized.durationSeconds,
      "agent": { "name": "OpenClaw Agent", "version": "unknown" },
      "tags": ["exported"],
    },
    "summary": {
      "steps": steps.length,
      "tools_used": tools,
      "errors": errors,
    },
    "steps": steps,
  };
}

const handler = async (event: any) => {
  try {
    if (event?.type !== "command" || event?.action !== "stop") return;

    const workspaceDir = event?.context?.workspaceDir;
    const sessionFile = event?.context?.sessionFile;

    if (!workspaceDir) {
      event?.messages?.push("📼 tape-export: workspaceDir missing; cannot export tape.");
      return;
    }
    if (!sessionFile) {
      event?.messages?.push("📼 tape-export: sessionFile missing; cannot export tape.");
      return;
    }

    const raw = await fs.readFile(sessionFile, "utf-8");
    const records = parseJsonl(raw);

    const normalized = normalizeOpenClawJsonl(records, path.basename(sessionFile));
    const tape = buildTapeV1(normalized);

    const outDir = path.join(workspaceDir, "tapes");
    await fs.mkdir(outDir, { recursive: true });

    const slug = slugify(normalized.title);
    const date = new Date().toISOString().slice(0, 10);
    const outPath = path.join(outDir, `${date}-${slug}.tape.json`);

    await fs.writeFile(outPath, JSON.stringify(tape, null, 2), "utf-8");

    event?.messages?.push(`📼 tape-export: wrote ${outPath}`);
  } catch (err: any) {
    console.error("[tape-export] failed:", err);
    try {
      event?.messages?.push(`📼 tape-export error: ${String(err?.message || err)}`);
    } catch {}
  }
};

export default handler;
