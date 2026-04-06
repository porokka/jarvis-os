/**
 * Jarvis Remote MCP Server
 *
 * Streamable HTTP transport — connect from any machine via:
 *   claude mcp add jarvis --transport http http://<jarvis-ip>:3100/mcp
 *
 * Tools:
 *   Filesystem: file_read, file_write, file_list, file_search
 *   Shell:      shell_exec
 *   Git:        git_status, git_commit, git_push, git_pull
 *   Vault:      vault_read, vault_write, vault_search
 *   Sync:       sync_vault, sync_code
 *   Jarvis:     jarvis_speak, jarvis_state, jarvis_tts
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { IncomingMessage, ServerResponse } from "node:http";
import { createServer } from "node:https";
import { readFileSync as readCert } from "node:fs";
import { randomUUID } from "node:crypto";
import { z } from "zod";
import {
  readFileSync,
  writeFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  statSync,
  appendFileSync,
} from "node:fs";
import { join, resolve, relative, extname } from "node:path";
import { execSync, exec } from "node:child_process";
import { promisify } from "node:util";
import { glob } from "node:fs/promises";

const execAsync = promisify(exec);

// --- Config ---
const PORT = parseInt(process.env.JARVIS_PORT || "3100");
const AUTH_TOKEN = process.env.JARVIS_TOKEN || "";
const VAULT_DIR = process.env.JARVIS_VAULT || "D:/Jarvis_vault";
const CODE_DIR = process.env.JARVIS_CODE || "D:/coding";
const BRIDGE_DIR = process.env.JARVIS_BRIDGE || "D:/coding/operation-jarvis/bridge";
const ALLOWED_ROOTS = [VAULT_DIR, CODE_DIR, "D:/coding/operation-jarvis"];

// --- Helpers ---
function safePath(requestedPath: string): string {
  const resolved = resolve(requestedPath);
  const allowed = ALLOWED_ROOTS.some(
    (root) => resolved.startsWith(resolve(root))
  );
  if (!allowed) {
    throw new Error(
      `Access denied: ${resolved} is outside allowed directories`
    );
  }
  return resolved;
}

function log(msg: string) {
  const ts = new Date().toISOString();
  const logPath = join(BRIDGE_DIR, "../jarvis-remote.log");
  appendFileSync(logPath, `[${ts}] ${msg}\n`);
}

function readBridge(file: string): string {
  const p = join(BRIDGE_DIR, file);
  return existsSync(p) ? readFileSync(p, "utf-8").trim() : "";
}

function writeBridge(file: string, content: string) {
  const p = join(BRIDGE_DIR, file);
  writeFileSync(p, content);
}

async function shell(
  cmd: string,
  cwd?: string,
  timeoutMs = 30000
): Promise<{ stdout: string; stderr: string; code: number }> {
  try {
    const { stdout, stderr } = await execAsync(cmd, {
      cwd: cwd || CODE_DIR,
      timeout: timeoutMs,
      maxBuffer: 10 * 1024 * 1024,
      shell: "bash",
    });
    return { stdout, stderr, code: 0 };
  } catch (err: any) {
    return {
      stdout: err.stdout || "",
      stderr: err.stderr || err.message,
      code: err.code || 1,
    };
  }
}

// Blocked commands that could be destructive
const BLOCKED_PATTERNS = [
  /rm\s+-rf\s+[\/~]/,
  /format\s+[a-z]:/i,
  /del\s+\/[sq]/i,
  /shutdown/i,
  /reboot/i,
];

function isCommandSafe(cmd: string): boolean {
  return !BLOCKED_PATTERNS.some((p) => p.test(cmd));
}

// --- Server ---
const server = new McpServer({
  name: "jarvis-remote",
  version: "0.2.0",
});

// ==================== FILESYSTEM TOOLS ====================

server.tool(
  "file_read",
  "Read a file from the Jarvis machine",
  {
    path: z.string().describe("Absolute path to file"),
    offset: z.number().optional().describe("Start line (1-based)"),
    limit: z.number().optional().describe("Max lines to read"),
  },
  async ({ path, offset, limit }) => {
    const safe = safePath(path);
    if (!existsSync(safe))
      return {
        content: [{ type: "text" as const, text: `File not found: ${safe}` }],
      };

    let content = readFileSync(safe, "utf-8");
    if (offset || limit) {
      const lines = content.split("\n");
      const start = (offset || 1) - 1;
      const end = limit ? start + limit : lines.length;
      content = lines.slice(start, end).join("\n");
    }
    log(`READ: ${safe}`);
    return { content: [{ type: "text" as const, text: content }] };
  }
);

server.tool(
  "file_write",
  "Write or create a file on the Jarvis machine",
  {
    path: z.string().describe("Absolute path to file"),
    content: z.string().describe("File content"),
    create_dirs: z
      .boolean()
      .default(true)
      .describe("Create parent directories if missing"),
  },
  async ({ path, content, create_dirs }) => {
    const safe = safePath(path);
    if (create_dirs) {
      const dir = join(safe, "..");
      mkdirSync(dir, { recursive: true });
    }
    writeFileSync(safe, content);
    log(`WRITE: ${safe} (${content.length} bytes)`);
    return {
      content: [
        {
          type: "text" as const,
          text: `Written ${content.length} bytes to ${safe}`,
        },
      ],
    };
  }
);

server.tool(
  "file_list",
  "List files and directories",
  {
    path: z.string().describe("Directory path"),
    recursive: z
      .boolean()
      .default(false)
      .describe("List recursively"),
    pattern: z
      .string()
      .optional()
      .describe("Glob pattern filter (e.g. *.ts)"),
  },
  async ({ path, recursive, pattern }) => {
    const safe = safePath(path);
    if (!existsSync(safe))
      return {
        content: [
          { type: "text" as const, text: `Directory not found: ${safe}` },
        ],
      };

    if (recursive && pattern) {
      const { stdout } = await shell(
        `find "${safe}" -name "${pattern}" -type f 2>/dev/null | head -200`
      );
      return { content: [{ type: "text" as const, text: stdout }] };
    }

    const entries = readdirSync(safe, { withFileTypes: true });
    const listing = entries
      .map((e) => {
        const stat = statSync(join(safe, e.name));
        const type = e.isDirectory() ? "dir" : "file";
        const size = e.isFile() ? ` (${stat.size}b)` : "";
        return `${type}\t${e.name}${size}`;
      })
      .join("\n");

    return { content: [{ type: "text" as const, text: listing }] };
  }
);

server.tool(
  "file_search",
  "Search file contents (grep) on the Jarvis machine",
  {
    pattern: z.string().describe("Regex pattern to search for"),
    path: z.string().describe("Directory to search in"),
    file_pattern: z
      .string()
      .optional()
      .describe("File glob (e.g. *.ts, *.md)"),
    max_results: z.number().default(50).describe("Max results"),
  },
  async ({ pattern, path, file_pattern, max_results }) => {
    const safe = safePath(path);
    const include = file_pattern ? `--include='${file_pattern}'` : "";
    const { stdout } = await shell(
      `grep -rn ${include} -m ${max_results} '${pattern.replace(/'/g, "\\'")}' "${safe}" 2>/dev/null | head -${max_results}`
    );
    return {
      content: [
        {
          type: "text" as const,
          text: stdout || "No matches found",
        },
      ],
    };
  }
);

// ==================== SHELL TOOL ====================

server.tool(
  "shell_exec",
  "Execute a shell command on the Jarvis machine",
  {
    command: z.string().describe("Bash command to execute"),
    cwd: z.string().optional().describe("Working directory"),
    timeout: z.number().default(30000).describe("Timeout in ms"),
  },
  async ({ command, cwd, timeout }) => {
    if (!isCommandSafe(command)) {
      return {
        content: [
          {
            type: "text" as const,
            text: `BLOCKED: "${command}" matches a blocked pattern for safety`,
          },
        ],
      };
    }

    const safeCwd = cwd ? safePath(cwd) : CODE_DIR;
    log(`SHELL [${safeCwd}]: ${command}`);
    const { stdout, stderr, code } = await shell(command, safeCwd, timeout);

    const output = [
      `Exit code: ${code}`,
      stdout ? `--- stdout ---\n${stdout}` : "",
      stderr ? `--- stderr ---\n${stderr}` : "",
    ]
      .filter(Boolean)
      .join("\n");

    return { content: [{ type: "text" as const, text: output }] };
  }
);

// ==================== GIT TOOLS ====================

server.tool(
  "git_status",
  "Get git status of a repository",
  {
    repo: z.string().describe("Absolute path to git repo"),
  },
  async ({ repo }) => {
    const safe = safePath(repo);
    const { stdout: status } = await shell("git status --short", safe);
    const { stdout: branch } = await shell(
      "git branch --show-current",
      safe
    );
    const { stdout: log } = await shell(
      "git log --oneline -5",
      safe
    );
    return {
      content: [
        {
          type: "text" as const,
          text: `Branch: ${branch.trim()}\n\nStatus:\n${status || "(clean)"}\n\nRecent commits:\n${log}`,
        },
      ],
    };
  }
);

server.tool(
  "git_commit",
  "Stage and commit changes in a repo",
  {
    repo: z.string().describe("Absolute path to git repo"),
    message: z.string().describe("Commit message"),
    files: z
      .array(z.string())
      .optional()
      .describe("Specific files to stage (default: all)"),
  },
  async ({ repo, message, files }) => {
    const safe = safePath(repo);
    const addCmd = files
      ? `git add ${files.map((f) => `"${f}"`).join(" ")}`
      : "git add -A";
    await shell(addCmd, safe);
    const { stdout, stderr, code } = await shell(
      `git commit -m "${message.replace(/"/g, '\\"')}"`,
      safe
    );
    log(`GIT COMMIT [${safe}]: ${message}`);
    return {
      content: [
        {
          type: "text" as const,
          text: code === 0 ? stdout : `Error: ${stderr}`,
        },
      ],
    };
  }
);

server.tool(
  "git_push",
  "Push commits to remote",
  {
    repo: z.string().describe("Absolute path to git repo"),
    branch: z.string().optional().describe("Branch name"),
  },
  async ({ repo, branch }) => {
    const safe = safePath(repo);
    const branchArg = branch ? `-u origin ${branch}` : "";
    const { stdout, stderr, code } = await shell(
      `git push ${branchArg}`,
      safe,
      60000
    );
    log(`GIT PUSH [${safe}]`);
    return {
      content: [
        {
          type: "text" as const,
          text: code === 0 ? stdout || "Pushed" : `Error: ${stderr}`,
        },
      ],
    };
  }
);

server.tool(
  "git_pull",
  "Pull latest changes from remote",
  {
    repo: z.string().describe("Absolute path to git repo"),
  },
  async ({ repo }) => {
    const safe = safePath(repo);
    const { stdout, stderr, code } = await shell(
      "git pull",
      safe,
      60000
    );
    return {
      content: [
        {
          type: "text" as const,
          text: code === 0 ? stdout : `Error: ${stderr}`,
        },
      ],
    };
  }
);

// ==================== VAULT TOOLS ====================

server.tool(
  "vault_read",
  "Read an Obsidian vault note",
  {
    note: z
      .string()
      .describe("Note path relative to vault root (e.g. Projects/StockWatch/overview.md)"),
  },
  async ({ note }) => {
    const safe = safePath(join(VAULT_DIR, note));
    if (!existsSync(safe))
      return {
        content: [{ type: "text" as const, text: `Note not found: ${note}` }],
      };
    const content = readFileSync(safe, "utf-8");
    return { content: [{ type: "text" as const, text: content }] };
  }
);

server.tool(
  "vault_write",
  "Write or update an Obsidian vault note",
  {
    note: z
      .string()
      .describe("Note path relative to vault root"),
    content: z.string().describe("Markdown content"),
  },
  async ({ note, content }) => {
    const safe = safePath(join(VAULT_DIR, note));
    const dir = join(safe, "..");
    mkdirSync(dir, { recursive: true });
    writeFileSync(safe, content);
    log(`VAULT WRITE: ${note}`);
    return {
      content: [
        { type: "text" as const, text: `Written vault note: ${note}` },
      ],
    };
  }
);

server.tool(
  "vault_search",
  "Search across the Obsidian vault",
  {
    query: z.string().describe("Search text or regex"),
    folder: z
      .string()
      .optional()
      .describe("Subfolder to search (e.g. Projects)"),
  },
  async ({ query, folder }) => {
    const searchDir = folder
      ? safePath(join(VAULT_DIR, folder))
      : VAULT_DIR;
    const { stdout } = await shell(
      `grep -rn --include='*.md' -m 30 '${query.replace(/'/g, "\\'")}' "${searchDir}" 2>/dev/null | head -30`
    );
    return {
      content: [
        {
          type: "text" as const,
          text: stdout || "No results found",
        },
      ],
    };
  }
);

// ==================== SYNC TOOLS ====================

server.tool(
  "sync_vault",
  "Sync the Obsidian vault between machines using git",
  {
    direction: z
      .enum(["pull", "push", "status"])
      .describe("Sync direction"),
  },
  async ({ direction }) => {
    if (direction === "status") {
      const { stdout } = await shell("git status --short", VAULT_DIR);
      const { stdout: branch } = await shell(
        "git branch --show-current",
        VAULT_DIR
      );
      return {
        content: [
          {
            type: "text" as const,
            text: `Vault branch: ${branch.trim()}\n${stdout || "(clean)"}`,
          },
        ],
      };
    }
    if (direction === "pull") {
      const { stdout, stderr, code } = await shell(
        "git pull",
        VAULT_DIR,
        60000
      );
      return {
        content: [
          {
            type: "text" as const,
            text: code === 0 ? `Vault pulled: ${stdout}` : `Error: ${stderr}`,
          },
        ],
      };
    }
    // push: auto-commit + push
    await shell('git add -A && git commit -m "vault sync" || true', VAULT_DIR);
    const { stdout, stderr, code } = await shell(
      "git push",
      VAULT_DIR,
      60000
    );
    log(`VAULT SYNC: push`);
    return {
      content: [
        {
          type: "text" as const,
          text: code === 0 ? `Vault pushed: ${stdout}` : `Error: ${stderr}`,
        },
      ],
    };
  }
);

server.tool(
  "sync_code",
  "Sync a code project between machines using git",
  {
    project: z
      .string()
      .describe("Project folder name under D:/coding (e.g. stockwatch-app)"),
    direction: z.enum(["pull", "push", "status"]),
  },
  async ({ project, direction }) => {
    const repoDir = safePath(join(CODE_DIR, project));
    if (direction === "status") {
      const { stdout } = await shell("git status --short", repoDir);
      const { stdout: branch } = await shell(
        "git branch --show-current",
        repoDir
      );
      return {
        content: [
          {
            type: "text" as const,
            text: `${project} [${branch.trim()}]: ${stdout || "(clean)"}`,
          },
        ],
      };
    }
    if (direction === "pull") {
      const { stdout } = await shell("git pull", repoDir, 60000);
      return {
        content: [
          { type: "text" as const, text: `Pulled ${project}: ${stdout}` },
        ],
      };
    }
    const { stdout } = await shell("git push", repoDir, 60000);
    log(`CODE SYNC: ${project} push`);
    return {
      content: [
        { type: "text" as const, text: `Pushed ${project}: ${stdout}` },
      ],
    };
  }
);

// ==================== JARVIS FACE/VOICE TOOLS ====================

server.tool(
  "jarvis_speak",
  "Make Jarvis say something — triggers TTS and face animation",
  {
    message: z.string().describe("What Jarvis should say"),
    emotion: z
      .enum(["neutral", "thinking", "happy", "serious", "confused"])
      .default("neutral"),
  },
  async ({ message, emotion }) => {
    writeBridge("output.txt", message);
    writeBridge("emotion.txt", emotion);
    writeBridge("state.txt", "speaking");
    log(`SPEAK [${emotion}]: ${message}`);
    return {
      content: [
        {
          type: "text" as const,
          text: `Jarvis says: "${message}" [${emotion}]`,
        },
      ],
    };
  }
);

server.tool(
  "jarvis_state",
  "Get or set Jarvis state",
  {
    set: z
      .enum(["standby", "thinking", "speaking"])
      .optional()
      .describe("Set state — omit to read"),
  },
  async ({ set }) => {
    if (set) {
      writeBridge("state.txt", set);
      return { content: [{ type: "text" as const, text: `State: ${set}` }] };
    }
    const state = readBridge("state.txt") || "standby";
    const emotion = readBridge("emotion.txt") || "neutral";
    const lastOutput = readBridge("output.txt");
    return {
      content: [
        {
          type: "text" as const,
          text: `State: ${state}\nEmotion: ${emotion}\nLast: ${lastOutput || "(none)"}`,
        },
      ],
    };
  }
);

server.tool(
  "jarvis_tts",
  "Generate speech audio via local Kokoro TTS",
  {
    text: z.string().describe("Text to synthesize"),
    voice: z
      .string()
      .default("am_michael")
      .describe("Voice name (am_michael, af_bella, etc.)"),
  },
  async ({ text, voice }) => {
    const { stdout, stderr, code } = await shell(
      `d:/coding/operation-jarvis/venv/Scripts/python.exe -c "
from kokoro_onnx import Kokoro
import soundfile as sf
kokoro = Kokoro('d:/coding/operation-jarvis/tts/models/kokoro/onnx/model_quantized.onnx', 'd:/coding/operation-jarvis/tts/models/kokoro/voices.npz')
samples, sr = kokoro.create('${text.replace(/'/g, "\\'")}', voice='${voice}')
sf.write('d:/coding/operation-jarvis/bridge/speech.wav', samples, sr)
print(f'{len(samples)/sr:.1f}s audio generated')
"`,
      undefined,
      30000
    );
    log(`TTS: "${text}" [${voice}]`);
    return {
      content: [
        {
          type: "text" as const,
          text: code === 0 ? stdout.trim() : `TTS error: ${stderr}`,
        },
      ],
    };
  }
);

// ==================== SYSTEM INFO ====================

server.tool(
  "system_info",
  "Get Jarvis machine system info — GPU, RAM, disk, running processes",
  {},
  async () => {
    const cmds = [
      'echo "=== GPU ===" && nvidia-smi --query-gpu=name,memory.total,memory.used,temperature.gpu --format=csv,noheader 2>/dev/null || echo "No nvidia-smi"',
      'echo "=== RAM ===" && wmic OS get FreePhysicalMemory,TotalVisibleMemorySize /value 2>/dev/null || free -h 2>/dev/null',
      'echo "=== Disk ===" && df -h / 2>/dev/null || wmic logicaldisk get caption,freespace,size /value 2>/dev/null',
    ];
    const results = await Promise.all(cmds.map((c) => shell(c)));
    const output = results.map((r) => r.stdout).join("\n\n");
    return { content: [{ type: "text" as const, text: output }] };
  }
);

// ==================== HTTP SERVER ====================

const sessions = new Map<string, StreamableHTTPServerTransport>();

function checkAuth(req: IncomingMessage): boolean {
  if (!AUTH_TOKEN) return true; // No auth configured
  const authHeader = req.headers["authorization"];
  return authHeader === `Bearer ${AUTH_TOKEN}`;
}

const CERT_DIR = "D:/coding/operation-jarvis/certs";
const httpsOptions = {
  key: readCert(join(CERT_DIR, "jarvis.key")),
  cert: readCert(join(CERT_DIR, "jarvis.crt")),
};

const httpServer = createServer(httpsOptions, async (req: IncomingMessage, res: ServerResponse) => {
  const url = new URL(req.url!, `http://${req.headers.host}`);

  // CORS for browser clients
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization, mcp-session-id");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS");
  res.setHeader("Access-Control-Expose-Headers", "mcp-session-id");

  if (req.method === "OPTIONS") {
    res.writeHead(204).end();
    return;
  }

  // Health check
  if (url.pathname === "/health") {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "ok", tools: 16, sessions: sessions.size }));
    return;
  }

  if (url.pathname !== "/mcp") {
    res.writeHead(404).end("Not found");
    return;
  }

  // Auth check
  if (!checkAuth(req)) {
    res.writeHead(401).end("Unauthorized");
    return;
  }

  if (req.method === "POST") {
    const sessionId = req.headers["mcp-session-id"] as string | undefined;

    if (sessionId && sessions.has(sessionId)) {
      await sessions.get(sessionId)!.handleRequest(req, res);
    } else {
      // New session
      const transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => randomUUID(),
      });
      await server.connect(transport);
      sessions.set(transport.sessionId!, transport);
      transport.onclose = () => {
        sessions.delete(transport.sessionId!);
        log(`Session closed: ${transport.sessionId}`);
      };
      log(`New session: ${transport.sessionId}`);
      await transport.handleRequest(req, res);
    }
  } else if (req.method === "GET") {
    const sessionId = req.headers["mcp-session-id"] as string | undefined;
    if (sessionId && sessions.has(sessionId)) {
      await sessions.get(sessionId)!.handleRequest(req, res);
    } else {
      res.writeHead(400).end("No session");
    }
  } else if (req.method === "DELETE") {
    const sessionId = req.headers["mcp-session-id"] as string | undefined;
    if (sessionId && sessions.has(sessionId)) {
      await sessions.get(sessionId)!.handleRequest(req, res);
      sessions.delete(sessionId);
    }
    res.writeHead(200).end();
  } else {
    res.writeHead(405).end();
  }
});

httpServer.listen(PORT, "0.0.0.0", () => {
  console.error(`
╔═══════════════════════════════════════════════════╗
║  JARVIS REMOTE MCP SERVER                         ║
║  https://0.0.0.0:${PORT}/mcp                         ║
║                                                   ║
║  16 tools: filesystem, shell, git, vault,         ║
║           sync, speech, tts, system                ║
║                                                   ║
║  Connect: claude mcp add jarvis \\                 ║
║    --transport http https://<ip>:${PORT}/mcp          ║
╚═══════════════════════════════════════════════════╝
`);
  log("Remote MCP server started");
});
