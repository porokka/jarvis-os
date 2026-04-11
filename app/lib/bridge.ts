/**
 * Jarvis Bridge — Server-side singleton managing the nervous system
 *
 * Handles:
 *  - State management (standby / thinking / speaking)
 *  - Input queue processing
 *  - Claude Code invocation via child process
 *  - File I/O for UE bridge compatibility
 *  - Emotion parsing from Claude responses
 *
 * All state lives in memory + mirrored to files for UE to poll.
 */

import { spawn } from "child_process";
import { writeFileSync, readFileSync, existsSync, mkdirSync, readdirSync } from "fs";
import { join } from "path";

export type JarvisState = "standby" | "thinking" | "speaking";
export type JarvisEmotion =
  | "neutral"
  | "thinking"
  | "happy"
  | "serious"
  | "confused";

export interface JarvisStatus {
  state: JarvisState;
  emotion: JarvisEmotion;
  lastInput: string;
  lastOutput: string;
  lastTimestamp: number;
  history: HistoryEntry[];
  brain: string;
}

export interface HistoryEntry {
  role: "user" | "jarvis";
  text: string;
  emotion?: JarvisEmotion;
  timestamp: number;
}

// Paths
const BRIDGE_DIR = join(process.cwd(), "..", "bridge");
const JARVIS_MD = join(process.cwd(), "..", "JARVIS.md");
const VAULT_DIR = "D:/Jarvis_vault";

// Ollama model mapping
const OLLAMA_MODELS = {
  fast: "qwen3:30b-a3b",
  code: "qwen3-coder:30b",
  reason: "qwen3:30b-a3b",
  deep: "llama3.1:70b",
};

// Keywords for routing (same as watcher.sh)
const CLAUDE_KEYWORDS = /subscription|use claude|ask claude|claude only/i;
const CODE_KEYWORDS = /debug|code|write|fix|refactor|pipeline|spark|script|function|error|bug|implement|class|import|syntax|compile|deploy|git|docker|python|bash|javascript|typescript|sql|api/i;
const DEEP_KEYWORDS = /strategy|analyse|analyze|research|summarize|summarise|document|report|architecture|compare|evaluate|should i|what do you think|explain why|business|plan|review my|audit/i;
const FAST_KEYWORDS = /joke|hello|hi|hey|time|weather|status|how are|what is|who is|tell me|play|open|volume|timer|thanks|good|morning|evening|night/i;

type BrainChoice = "claude" | "ollama_fast" | "ollama_code" | "ollama_reason" | "ollama_deep";

class JarvisBridge {
  private state: JarvisState = "standby";
  private emotion: JarvisEmotion = "neutral";
  private lastInput = "";
  private lastOutput = "";
  private lastTimestamp = 0;
  private brain: BrainChoice = "claude";
  private history: HistoryEntry[] = [];
  private processing = false;
  private listeners: Set<() => void> = new Set();

  constructor() {
    // Ensure bridge dir exists for UE file polling
    if (!existsSync(BRIDGE_DIR)) {
      mkdirSync(BRIDGE_DIR, { recursive: true });
    }
    this.syncFiles();
  }

  getStatus(): JarvisStatus {
    return {
      state: this.state,
      emotion: this.emotion,
      lastInput: this.lastInput,
      lastOutput: this.lastOutput,
      lastTimestamp: this.lastTimestamp,
      brain: this.brain,
      history: this.history.slice(-50),
    };
  }

  /**
   * Route input to the right brain based on keywords and length.
   */
  private route(text: string): BrainChoice {
    if (CLAUDE_KEYWORDS.test(text)) return "claude";
    if (CODE_KEYWORDS.test(text)) return "ollama_code";
    if (DEEP_KEYWORDS.test(text)) return "ollama_deep";
    if (FAST_KEYWORDS.test(text)) return "ollama_fast";
    const words = text.split(/\s+/).length;
    if (words >= 20) return "ollama_deep";
    if (words >= 10) return "ollama_reason";
    return "ollama_fast";
  }

  /**
   * Read a file from the vault, return empty string if missing.
   */
  private readVaultFile(relativePath: string): string {
    try {
      const fullPath = join(VAULT_DIR, relativePath);
      if (existsSync(fullPath)) {
        return readFileSync(fullPath, "utf-8").trim();
      }
    } catch {}
    return "";
  }

  /**
   * Load personality from JARVIS.md in the project root.
   */
  private loadPersonality(): string {
    try {
      if (existsSync(JARVIS_MD)) {
        return readFileSync(JARVIS_MD, "utf-8").trim();
      }
    } catch {}
    return "You are JARVIS, a local AI assistant. Be concise and direct.";
  }

  /**
   * List files in a vault directory recursively (max depth 2).
   */
  private listVaultDir(dir: string, depth = 0): string[] {
    const results: string[] = [];
    try {
      const fullPath = join(VAULT_DIR, dir);
      if (!existsSync(fullPath)) return results;
      const entries = readdirSync(fullPath, { withFileTypes: true });
      for (const entry of entries) {
        const rel = join(dir, entry.name);
        if (entry.name.startsWith(".") || entry.name === "node_modules") continue;
        if (entry.isDirectory() && depth < 2) {
          results.push(rel + "/");
          results.push(...this.listVaultDir(rel, depth + 1));
        } else if (entry.isFile() && entry.name.endsWith(".md")) {
          results.push(rel);
        }
      }
    } catch {}
    return results;
  }

  /**
   * Load relevant vault context based on user input.
   * Always includes user profile + active projects.
   * Keyword-matches to load specific project details.
   * Vault-wide queries get a full directory listing.
   */
  private loadVaultContext(userText: string): string {
    const sections: string[] = [];
    const lower = userText.toLowerCase();

    // User profile — always loaded
    const userProfile = this.readVaultFile("People/sami.md");
    if (userProfile) {
      sections.push("## Owner\n" + userProfile);
    }

    // Active projects summary from CLAUDE.md — always loaded
    const vaultIndex = this.readVaultFile("CLAUDE.md");
    if (vaultIndex) {
      const projectsMatch = vaultIndex.match(/## Active Projects[\s\S]*$/);
      if (projectsMatch) {
        sections.push(projectsMatch[0]);
      }
    }

    // Vault-wide queries: load directory structure + references
    const vaultKeywords = ["vault", "memory", "notes", "obsidian", "what do you know", "what projects", "check your"];
    if (vaultKeywords.some((k) => lower.includes(k))) {
      const files = this.listVaultDir("");
      if (files.length > 0) {
        sections.push("## Vault Contents\n```\n" + files.join("\n") + "\n```");
      }
      // Also load all references
      const refFiles = files.filter((f) => f.startsWith("References/") && f.endsWith(".md"));
      for (const ref of refFiles) {
        const content = this.readVaultFile(ref);
        if (content) {
          sections.push(`## ${ref}\n${content.slice(0, 600)}`);
        }
      }
    }

    // "who am i" / identity queries: load full user profile
    const identityKeywords = ["who am i", "know me", "remember me", "my name", "about me", "my projects"];
    if (identityKeywords.some((k) => lower.includes(k))) {
      // Profile already loaded above, add project overviews
      const projectDirs = this.listVaultDir("Projects").filter((f) => f.endsWith("/"));
      for (const dir of projectDirs.slice(0, 5)) {
        const overview =
          this.readVaultFile(join(dir, "overview.md")) ||
          this.readVaultFile(join(dir, dir.split("/").filter(Boolean).pop() + ".md"));
        if (overview) {
          sections.push(`## ${dir}\n${overview.slice(0, 400)}`);
        }
      }
    }

    // Project-specific keyword matching
    const projectFolders = [
      { keywords: ["stockwatch", "bullish", "stock", "prediction"], folder: "Projects/StockWatch" },
      { keywords: ["caskra", "beverage", "brew"], folder: "Projects/Caskra" },
      { keywords: ["social media", "social"], folder: "Projects/SocialMediaManager" },
      { keywords: ["tender"], folder: "Projects/TenderApp" },
      { keywords: ["travel"], folder: "Projects/TravelBook" },
      { keywords: ["poro-it", "company", "website"], folder: "Projects/PoroIT" },
      { keywords: ["rest api", "kettle", "impala", "varha"], folder: "Projects/RestAPI" },
      { keywords: ["dravn", "api platform", "pipeline"], folder: "Projects/APIPlatform" },
      { keywords: ["jarvis", "assistant", "metahuman"], folder: "Projects/OperationJarvis" },
    ];

    for (const { keywords, folder } of projectFolders) {
      if (keywords.some((k) => lower.includes(k))) {
        const overview =
          this.readVaultFile(join(folder, "overview.md")) ||
          this.readVaultFile(
            join(folder, folder.split("/").pop() + ".md")
          );
        if (overview) {
          sections.push("## Relevant Project Context\n" + overview.slice(0, 1500));
        }
        const decisions = this.readVaultFile(join(folder, "decisions.md"));
        if (decisions) {
          sections.push("## Past Decisions\n" + decisions.slice(0, 800));
        }
        break;
      }
    }

    return sections.length > 0
      ? "\n\n## Vault Memory (pre-loaded, do NOT pretend to check files — this IS the data)\n" + sections.join("\n\n")
      : "";
  }

  /**
   * Process user input: route to brain, build prompt with vault context, invoke.
   */
  async processInput(text: string): Promise<string> {
    if (this.processing) {
      return "I'm still thinking about the last thing you said. One moment.";
    }

    this.processing = true;
    this.lastInput = text;
    this.lastTimestamp = Date.now();
    this.brain = this.route(text);
    this.setState("thinking", "thinking");

    console.log(`[BRIDGE] Router → ${this.brain}`);

    this.history.push({
      role: "user",
      text,
      timestamp: Date.now(),
    });

    try {
      const response = await this.callBrain(text);
      const { cleanText, emotion } = this.parseResponse(response);

      this.lastOutput = cleanText;
      this.setState("speaking", emotion);

      this.history.push({
        role: "jarvis",
        text: cleanText,
        emotion,
        timestamp: Date.now(),
      });

      return cleanText;
    } catch (err: any) {
      const errorMsg = "Something went wrong on my end. Try again.";
      this.lastOutput = errorMsg;
      this.setState("standby", "confused");
      console.error("[BRIDGE] Error:", err.message);
      return errorMsg;
    } finally {
      this.processing = false;
    }
  }

  /**
   * Mark speaking as done — called after TTS finishes
   */
  finishSpeaking() {
    this.setState("standby", "neutral");
  }

  /**
   * Set emotion without speaking (for UE face control)
   */
  setEmotion(emotion: JarvisEmotion) {
    this.emotion = emotion;
    this.syncFiles();
    this.notifyListeners();
  }

  /**
   * Subscribe to state changes (for SSE)
   */
  subscribe(callback: () => void): () => void {
    this.listeners.add(callback);
    return () => this.listeners.delete(callback);
  }

  // --- Private ---

  private setState(state: JarvisState, emotion: JarvisEmotion) {
    this.state = state;
    this.emotion = emotion;
    this.syncFiles();
    this.notifyListeners();
  }

  private notifyListeners() {
    for (const cb of this.listeners) {
      try {
        cb();
      } catch {}
    }
  }

  /**
   * Call Ollama API directly for chat/knowledge queries.
   * We feed it vault context — it has no file access itself.
   */
  private async callOllama(userText: string, model: string): Promise<string> {
    const personality = this.loadPersonality();
    const vaultContext = this.loadVaultContext(userText);

    const messages = [
      {
        role: "system",
        content: `${personality}\n${vaultContext}\n\nPlain text only, no markdown. Max 3 sentences.`,
      },
      // Include recent history as messages
      ...this.history.slice(-10).map((h) => ({
        role: h.role === "user" ? "user" : "assistant",
        content: h.text,
      })),
      { role: "user", content: userText },
    ];

    console.log(`[BRIDGE] Ollama → ${model}`);

    const res = await fetch("http://localhost:7900/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model, messages, stream: false }),
    });

    if (!res.ok) {
      throw new Error(`Ollama ${res.status}: ${await res.text()}`);
    }

    const data = await res.json();
    return data.message?.content?.trim() || "";
  }

  /**
   * Call Claude Code via subprocess for code tasks.
   * Has full file access, bash, tools — the real deal.
   */
  private async callClaudeCode(userText: string): Promise<string> {
    const personality = this.loadPersonality();

    const historyContext = this.history
      .slice(-6)
      .map((h) =>
        h.role === "user" ? `User: ${h.text}` : `Jarvis: ${h.text}`
      )
      .join("\n");

    const prompt = `${personality}

## Recent conversation
${historyContext || "(none)"}

---
User said: ${userText}

Respond as JARVIS. Plain text only, no markdown. Max 3 sentences unless code detail is needed.`;

    console.log("[BRIDGE] Claude Code (Anthropic, full tools)");

    return new Promise((resolve, reject) => {
      const isWindows = process.platform === "win32";
      const cmd = isWindows ? "wsl" : "claude";
      const args = isWindows ? ["claude", "--print"] : ["--print"];

      const child = spawn(cmd, args, {
        shell: true,
        timeout: 60000,
      });

      let stdout = "";
      let stderr = "";

      child.stdin.write(prompt);
      child.stdin.end();

      child.stdout.on("data", (data: Buffer) => {
        stdout += data.toString();
      });

      child.stderr.on("data", (data: Buffer) => {
        stderr += data.toString();
      });

      child.on("close", (code: number | null) => {
        if (code === 0 && stdout.trim()) {
          resolve(stdout.trim());
        } else {
          reject(
            new Error(`Claude exited with code ${code}: ${stderr.trim()}`)
          );
        }
      });

      child.on("error", reject);
    });
  }

  /**
   * Route to the right backend based on brain choice.
   */
  private async callBrain(userText: string): Promise<string> {
    switch (this.brain) {
      case "ollama_fast":   return this.callOllama(userText, OLLAMA_MODELS.fast);
      case "ollama_reason": return this.callOllama(userText, OLLAMA_MODELS.reason);
      case "ollama_deep":   return this.callOllama(userText, OLLAMA_MODELS.deep);
      case "ollama_code":   return this.callClaudeCode(userText);
      case "claude":        return this.callClaudeCode(userText);
    }
  }

  private parseResponse(response: string): {
    cleanText: string;
    emotion: JarvisEmotion;
  } {
    const lines = response.split("\n");
    let emotion: JarvisEmotion = "neutral";
    const textLines: string[] = [];

    for (const line of lines) {
      const trimmed = line.trim();
      const match = trimmed.match(/^\[EMOTION:(.*?)\]$/);
      if (match) {
        const e = match[1].toLowerCase();
        if (
          ["neutral", "thinking", "happy", "serious", "confused"].includes(e)
        ) {
          emotion = e as JarvisEmotion;
        }
      } else {
        textLines.push(line);
      }
    }

    return {
      cleanText: textLines.join("\n").trim(),
      emotion,
    };
  }

  /**
   * Mirror state to files so UE Python bridge can poll them
   */
  private syncFiles() {
    try {
      writeFileSync(join(BRIDGE_DIR, "state.txt"), this.state);
      writeFileSync(join(BRIDGE_DIR, "emotion.txt"), this.emotion);
      writeFileSync(join(BRIDGE_DIR, "output.txt"), this.lastOutput);
      writeFileSync(join(BRIDGE_DIR, "last_input.txt"), this.lastInput);
    } catch {
      // Bridge dir may not exist in dev — that's fine
    }
  }
}

// Singleton
const globalBridge = globalThis as typeof globalThis & {
  __jarvisBridge?: JarvisBridge;
};

if (!globalBridge.__jarvisBridge) {
  globalBridge.__jarvisBridge = new JarvisBridge();
}

export const bridge: JarvisBridge = globalBridge.__jarvisBridge;
