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

import { execSync, spawn } from "child_process";
import { writeFileSync, existsSync, mkdirSync } from "fs";
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
}

export interface HistoryEntry {
  role: "user" | "jarvis";
  text: string;
  emotion?: JarvisEmotion;
  timestamp: number;
}

// Bridge files directory (for UE compatibility)
const BRIDGE_DIR = join(process.cwd(), "..", "bridge");
const JARVIS_MD = join(process.cwd(), "..", "JARVIS.md");

class JarvisBridge {
  private state: JarvisState = "standby";
  private emotion: JarvisEmotion = "neutral";
  private lastInput = "";
  private lastOutput = "";
  private lastTimestamp = 0;
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
      history: this.history.slice(-50), // last 50 entries
    };
  }

  /**
   * Process user input through Claude and return the response.
   * This is the main pipeline: input → Claude → parse → output
   */
  async processInput(text: string): Promise<string> {
    if (this.processing) {
      return "I'm still thinking about the last thing you said. One moment.";
    }

    this.processing = true;
    this.lastInput = text;
    this.lastTimestamp = Date.now();
    this.setState("thinking", "thinking");

    this.history.push({
      role: "user",
      text,
      timestamp: Date.now(),
    });

    try {
      const response = await this.callClaude(text);
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
      console.error("[BRIDGE] Claude error:", err.message);
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

  private async callClaude(userText: string): Promise<string> {
    // Build context with recent history
    const historyContext = this.history
      .slice(-10)
      .map((h) =>
        h.role === "user" ? `User: ${h.text}` : `Jarvis: ${h.text}`
      )
      .join("\n");

    const prompt = `You are JARVIS — a local AI assistant for Sami Porokka.

## Personality
- Concise, direct, slightly dry wit. Like the MCU JARVIS but less formal.
- Never say "as an AI" or "I don't have feelings." Just answer.
- Keep responses under 3 sentences unless asked for detail.
- When unsure, say so briefly. Don't hallucinate.

## Response format
- Write ONLY your spoken response as plain text
- No markdown, no code blocks, no formatting — just speech
- If appropriate, prefix with [EMOTION:thinking|happy|serious|confused] on its own line

## Recent conversation
${historyContext || "(none)"}

---
User said: ${userText}

Respond as JARVIS:`;

    return new Promise((resolve, reject) => {
      const child = spawn("claude", ["--print"], {
        shell: true,
        timeout: 30000,
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
