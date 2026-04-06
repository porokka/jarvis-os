/**
 * Jarvis MCP Server
 *
 * Exposes the file bridge as MCP tools so Claude Code can:
 * - Send speech to Jarvis (→ bridge/output.txt → TTS + UE face)
 * - Read/set state (standby / thinking / speaking)
 * - Set face emotion without speaking
 * - Read last input (what the user said via voice/CLI)
 *
 * File protocol:
 *   input.txt      ← voice/CLI writes here, watcher.sh reads it
 *   output.txt     ← Claude writes here, TTS + UE reads it
 *   state.txt      ← standby | thinking | speaking
 *   last_input.txt ← copy of last command for context
 *   emotion.txt    ← neutral | thinking | happy | serious | confused
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { readFileSync, writeFileSync, existsSync, appendFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const JARVIS_DIR = join(__dirname, "../..");
const FILES = {
  input: join(JARVIS_DIR, "input.txt"),
  output: join(JARVIS_DIR, "output.txt"),
  state: join(JARVIS_DIR, "state.txt"),
  lastInput: join(JARVIS_DIR, "last_input.txt"),
  emotion: join(JARVIS_DIR, "emotion.txt"),
  log: join(JARVIS_DIR, "jarvis.log"),
};

function readFile(path: string): string {
  return existsSync(path) ? readFileSync(path, "utf-8").trim() : "";
}

function log(msg: string) {
  const ts = new Date().toISOString();
  appendFileSync(FILES.log, `[${ts}] ${msg}\n`);
}

const server = new McpServer({
  name: "jarvis",
  version: "0.1.0",
});

// --- jarvis_speak: Write response for TTS + UE face ---
server.tool(
  "jarvis_speak",
  "Make Jarvis say something — writes to output.txt for TTS and UE face to pick up",
  {
    message: z.string().describe("What Jarvis should say"),
    emotion: z
      .enum(["neutral", "thinking", "happy", "serious", "confused"])
      .default("neutral")
      .describe("Facial emotion to display while speaking"),
  },
  async ({ message, emotion }) => {
    writeFileSync(FILES.output, message);
    writeFileSync(FILES.emotion, emotion);
    writeFileSync(FILES.state, "speaking");
    log(`SPEAK [${emotion}]: ${message}`);
    return {
      content: [{ type: "text" as const, text: `Jarvis says: "${message}" [${emotion}]` }],
    };
  }
);

// --- jarvis_emotion: Change face without speaking ---
server.tool(
  "jarvis_emotion",
  "Change Jarvis face emotion without speaking",
  {
    emotion: z.enum(["neutral", "thinking", "happy", "serious", "confused"]),
  },
  async ({ emotion }) => {
    writeFileSync(FILES.emotion, emotion);
    log(`EMOTION: ${emotion}`);
    return {
      content: [{ type: "text" as const, text: `Expression: ${emotion}` }],
    };
  }
);

// --- jarvis_state: Read or set bridge state ---
server.tool(
  "jarvis_state",
  "Get or set Jarvis state (standby / thinking / speaking)",
  {
    set: z
      .enum(["standby", "thinking", "speaking"])
      .optional()
      .describe("Set state — omit to just read current state"),
  },
  async ({ set }) => {
    if (set) {
      writeFileSync(FILES.state, set);
      log(`STATE → ${set}`);
      return { content: [{ type: "text" as const, text: `State: ${set}` }] };
    }
    const state = readFile(FILES.state) || "standby";
    const emotion = readFile(FILES.emotion) || "neutral";
    const lastInput = readFile(FILES.lastInput);
    const lastOutput = readFile(FILES.output);
    const summary = [
      `State: ${state}`,
      `Emotion: ${emotion}`,
      lastInput ? `Last heard: "${lastInput}"` : "No input yet",
      lastOutput ? `Last said: "${lastOutput}"` : "No output yet",
    ].join("\n");
    return { content: [{ type: "text" as const, text: summary }] };
  }
);

// --- jarvis_listen: Read what user said last ---
server.tool(
  "jarvis_listen",
  "Read what the user last said (from last_input.txt)",
  {},
  async () => {
    const input = readFile(FILES.lastInput);
    if (!input) {
      return { content: [{ type: "text" as const, text: "Nothing heard yet" }] };
    }
    return { content: [{ type: "text" as const, text: input }] };
  }
);

// --- jarvis_log: Read recent log entries ---
server.tool(
  "jarvis_log",
  "Read recent Jarvis activity log",
  {
    lines: z.number().default(20).describe("Number of recent lines to read"),
  },
  async ({ lines }) => {
    const logContent = readFile(FILES.log);
    if (!logContent) {
      return { content: [{ type: "text" as const, text: "No log entries yet" }] };
    }
    const recent = logContent.split("\n").slice(-lines).join("\n");
    return { content: [{ type: "text" as const, text: recent }] };
  }
);

// --- Start ---
async function main() {
  // Initialize files if they don't exist
  for (const [key, path] of Object.entries(FILES)) {
    if (!existsSync(path)) {
      writeFileSync(path, key === "state" ? "standby" : key === "emotion" ? "neutral" : "");
    }
  }

  const transport = new StdioServerTransport();
  await server.connect(transport);
  log("MCP server started");
  console.error("Jarvis MCP Server running — 5 tools registered");
}

main().catch((err) => {
  console.error("Fatal:", err);
  process.exit(1);
});
