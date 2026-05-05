// Copy this file to .opencode/plugins/agent-tts.js to enable it for OpenCode.
//
// It is intentionally conservative: it waits for a session.idle event and then
// speaks the latest assistant message captured from message.updated events.

import { mkdtemp, writeFile } from "node:fs/promises"
import { tmpdir } from "node:os"
import { join, resolve } from "node:path"
import { spawn } from "node:child_process"

function messageID(info) {
  return info?.id || info?.messageID || info?.metadata?.id || ""
}

function sessionIDFromInfo(info) {
  return info?.sessionID || info?.session?.id || info?.metadata?.sessionID || "default"
}

function roleOf(info) {
  return String(info?.role || info?.type || info?.metadata?.role || "").toLowerCase()
}

function textFromPart(part) {
  if (!part) return ""
  if (part.type && part.type !== "text") return ""
  return part.text || part.content || part.value || ""
}

function textFromMessage(info) {
  if (!info) return ""
  if (typeof info.text === "string") return info.text
  if (typeof info.content === "string") return info.content

  const parts = info.parts || info.message?.parts || []
  if (!Array.isArray(parts)) return ""
  return parts.map(textFromPart).filter(Boolean).join("")
}

async function writeTempResponse(text) {
  const dir = await mkdtemp(join(tmpdir(), "opencode-agent-tts-"))
  const path = join(dir, "response.txt")
  await writeFile(path, text, "utf8")
  return path
}

export const AgentTTSPlugin = async ({ directory, worktree }) => {
  const repoRoot = resolve(process.env.AGENT_TTS_REPO || worktree || directory)
  const python = process.env.AGENT_TTS_PYTHON || "python3"
  const script = resolve(process.env.AGENT_TTS_SCRIPT || join(repoRoot, "scripts", "agent_tts.py"))
  const logPath = process.env.AGENT_TTS_LOG || join(tmpdir(), "baba_agent_tts.log")
  const latestBySession = new Map()
  const spokenMessages = new Set()

  async function speak(sessionID) {
    const latest = latestBySession.get(sessionID) || latestBySession.get("default")
    if (!latest || !latest.text.trim() || spokenMessages.has(latest.key)) return
    spokenMessages.add(latest.key)

    const textFile = await writeTempResponse(latest.text)
    const child = spawn(
      python,
      [
        script,
        "--background",
        "--no-echo",
        "--text-file",
        textFile,
        "--cleanup-text-file",
        "--background-log",
        logPath,
      ],
      {
        cwd: repoRoot,
        detached: true,
        env: process.env,
        stdio: "ignore",
      },
    )
    child.unref()
  }

  return {
    event: async ({ event }) => {
      if (event.type === "message.updated") {
        const info = event.properties?.info || event.properties?.message
        if (!roleOf(info).includes("assistant")) return

        const text = textFromMessage(info)
        if (!text.trim()) return

        const sessionID = sessionIDFromInfo(info)
        latestBySession.set(sessionID, {
          text,
          key: `${sessionID}:${messageID(info) || text.length}`,
        })
      }

      if (event.type === "session.idle") {
        const sessionID =
          event.properties?.sessionID ||
          event.properties?.session?.id ||
          event.properties?.info?.sessionID ||
          "default"
        await speak(sessionID)
      }
    },
  }
}
