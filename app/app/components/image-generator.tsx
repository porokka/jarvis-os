"use client";

import { useState, useCallback, useRef } from "react";

// ─── ComfyUI FLUX Workflow Template ───
function buildFluxWorkflow(prompt: string) {
  return {
    "1": {
      class_type: "CheckpointLoaderSimple",
      inputs: {
        ckpt_name: "flux1-dev.safetensors",
      },
    },
    "2": {
      class_type: "CLIPTextEncode",
      inputs: {
        text: prompt,
        clip: ["1", 1],
      },
    },
    "3": {
      class_type: "CLIPTextEncode",
      inputs: {
        text: "",
        clip: ["1", 1],
      },
    },
    "4": {
      class_type: "EmptyLatentImage",
      inputs: {
        width: 1024,
        height: 1024,
        batch_size: 1,
      },
    },
    "5": {
      class_type: "KSampler",
      inputs: {
        seed: Math.floor(Math.random() * 2 ** 32),
        steps: 20,
        cfg: 3.5,
        sampler_name: "euler",
        scheduler: "normal",
        denoise: 1.0,
        model: ["1", 0],
        positive: ["2", 0],
        negative: ["3", 0],
        latent_image: ["4", 0],
      },
    },
    "6": {
      class_type: "VAEDecode",
      inputs: {
        samples: ["5", 0],
        vae: ["1", 2],
      },
    },
    "7": {
      class_type: "SaveImage",
      inputs: {
        filename_prefix: "jarvis_flux",
        images: ["6", 0],
      },
    },
  };
}

// ─── State types ───
type Stage = "input" | "enhancing" | "enhanced" | "generating" | "done" | "error";

const OLLAMA_URL = "http://localhost:11434";
const COMFYUI_URL = "http://localhost:8188";

const ENHANCE_SYSTEM = `You are an expert image prompt engineer for FLUX AI image generation.
Rewrite the user's rough description into a detailed, high-quality image generation prompt.
Include: subject description, art style, lighting, composition, camera angle, color palette, mood, texture details.
Keep it under 200 words. Output ONLY the enhanced prompt, nothing else. No explanations, no markdown.`;

export function ImageGenerator() {
  const [userInput, setUserInput] = useState("");
  const [enhancedPrompt, setEnhancedPrompt] = useState("");
  const [stage, setStage] = useState<Stage>("input");
  const [error, setError] = useState("");
  const [imageUrl, setImageUrl] = useState("");
  const [progress, setProgress] = useState("");
  const abortRef = useRef<AbortController | null>(null);

  // ─── Step 1: Enhance prompt via Ollama ───
  const enhancePrompt = useCallback(async () => {
    if (!userInput.trim()) return;

    setStage("enhancing");
    setError("");
    setEnhancedPrompt("");

    try {
      const res = await fetch(`${OLLAMA_URL}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "qwen3:latest",
          prompt: userInput,
          system: ENHANCE_SYSTEM,
          stream: false,
          options: { num_predict: 300 },
        }),
      });

      if (!res.ok) throw new Error(`Ollama returned ${res.status}`);

      const data = await res.json();
      let enhanced = data.response?.trim() || "";

      // Strip thinking tags if present
      if (enhanced.includes("<think>")) {
        enhanced = enhanced.replace(/<think>[\s\S]*?<\/think>/g, "").trim();
      }

      if (!enhanced) throw new Error("Empty response from Ollama");

      setEnhancedPrompt(enhanced);
      setStage("enhanced");
    } catch (e) {
      setError(
        e instanceof TypeError
          ? "Cannot reach Ollama at localhost:11434. Is it running?"
          : `Prompt enhancement failed: ${e instanceof Error ? e.message : String(e)}`
      );
      setStage("error");
    }
  }, [userInput]);

  // ─── VRAM swap: unload Ollama models before ComfyUI ───
  const unloadOllama = async () => {
    try {
      // Set keepalive to 0 to unload
      await fetch(`${OLLAMA_URL}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: "qwen3:30b-a3b", keep_alive: 0 }),
      });
      // Wait for VRAM to free
      await new Promise((r) => setTimeout(r, 3000));
    } catch {}
  };

  const reloadOllama = async () => {
    try {
      await fetch(`${OLLAMA_URL}/api/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ model: "qwen3:30b-a3b", prompt: "", keep_alive: -1 }),
      });
    } catch {}
  };

  // ─── Step 2: Generate image via ComfyUI ───
  const generateImage = useCallback(async (prompt: string) => {
    setStage("generating");
    setError("");
    setImageUrl("");
    setProgress("Freeing GPU memory...");

    try {
      // Unload Ollama to free VRAM for FLUX
      await unloadOllama();
      setProgress("Queuing workflow...");

      // Submit workflow
      const workflow = buildFluxWorkflow(prompt);
      const queueRes = await fetch(`${COMFYUI_URL}/prompt`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ prompt: workflow }),
      });

      if (!queueRes.ok) {
        const errText = await queueRes.text();
        throw new Error(`ComfyUI queue failed (${queueRes.status}): ${errText.slice(0, 200)}`);
      }

      const { prompt_id } = await queueRes.json();
      if (!prompt_id) throw new Error("No prompt_id returned from ComfyUI");

      setProgress("Generating image...");

      // Poll for completion
      const controller = new AbortController();
      abortRef.current = controller;

      let attempts = 0;
      const maxAttempts = 150; // 5 minutes at 2s intervals

      while (attempts < maxAttempts) {
        if (controller.signal.aborted) return;

        await new Promise((r) => setTimeout(r, 2000));
        attempts++;

        const histRes = await fetch(`${COMFYUI_URL}/history/${prompt_id}`, {
          signal: controller.signal,
        });

        if (!histRes.ok) continue;

        const history = await histRes.json();
        const entry = history[prompt_id];

        if (!entry) {
          setProgress(`Generating image... (${attempts * 2}s)`);
          continue;
        }

        if (entry.status?.status_str === "error") {
          throw new Error("ComfyUI generation failed. Check ComfyUI logs.");
        }

        // Find output image
        const outputs = entry.outputs;
        if (!outputs) continue;

        for (const nodeId of Object.keys(outputs)) {
          const images = outputs[nodeId]?.images;
          if (images && images.length > 0) {
            const img = images[0];
            const viewUrl = `${COMFYUI_URL}/view?filename=${encodeURIComponent(img.filename)}&subfolder=${encodeURIComponent(img.subfolder || "")}&type=${encodeURIComponent(img.type || "output")}`;
            setImageUrl(viewUrl);
            setStage("done");
            return;
          }
        }

        setProgress(`Generating image... (${attempts * 2}s)`);
      }

      throw new Error("Generation timed out after 5 minutes");
    } catch (e) {
      if ((e as Error).name === "AbortError") {
        await reloadOllama();
        return;
      }
      setError(
        e instanceof TypeError
          ? "Cannot reach ComfyUI at localhost:8188. Is it running?"
          : `Image generation failed: ${e instanceof Error ? e.message : String(e)}`
      );
      setStage("error");
      // Reload Ollama even on error
      await reloadOllama();
    }
  }, []);

  // ─── Actions ───
  const handleGenerate = () => enhancePrompt();
  const handleConfirmGenerate = () => generateImage(enhancedPrompt);

  const handleRedo = () => {
    setImageUrl("");
    setStage("generating");
    generateImage(enhancedPrompt);
  };

  const handleAccept = () => {
    if (!imageUrl) return;
    const a = document.createElement("a");
    a.href = imageUrl;
    a.download = `jarvis_flux_${Date.now()}.png`;
    a.click();
    // Reload Ollama after done with image gen
    reloadOllama();
  };

  const handleDiscard = () => {
    abortRef.current?.abort();
    setStage("input");
    setEnhancedPrompt("");
    setImageUrl("");
    setError("");
    setProgress("");
    // Reload Ollama
    reloadOllama();
  };

  const handleEditPrompt = () => setStage("enhanced");

  return (
    <div className="ig-container">
      {/* ─── Input Stage ─── */}
      {(stage === "input" || stage === "error") && (
        <div className="ig-input-area">
          <h2 className="ig-title">AI IMAGE GENERATOR</h2>
          <p className="ig-subtitle">Describe what you want — Qwen3 enhances it, FLUX generates it</p>

          <textarea
            className="ig-textarea"
            value={userInput}
            onChange={(e) => setUserInput(e.target.value)}
            placeholder="e.g. image for instagram a kombucha brand called Alchemians with golden liquid in a glass bottle, botanical vibes"
            rows={4}
          />

          <button
            className="ig-btn ig-btn-primary"
            onClick={handleGenerate}
            disabled={!userInput.trim()}
          >
            GENERATE
          </button>

          {error && (
            <div className="ig-error">
              <span className="ig-error-icon">!</span>
              {error}
            </div>
          )}
        </div>
      )}

      {/* ─── Enhancing Stage ─── */}
      {stage === "enhancing" && (
        <div className="ig-loading">
          <div className="ig-spinner" />
          <p className="ig-loading-text">Enhancing prompt with Qwen3...</p>
          <p className="ig-loading-sub">Optimizing for FLUX image generation</p>
        </div>
      )}

      {/* ─── Enhanced Prompt Review ─── */}
      {stage === "enhanced" && (
        <div className="ig-review">
          <h3 className="ig-review-title">ENHANCED PROMPT</h3>
          <div className="ig-prompt-box">
            <textarea
              className="ig-prompt-edit"
              value={enhancedPrompt}
              onChange={(e) => setEnhancedPrompt(e.target.value)}
              rows={6}
            />
          </div>
          <div className="ig-review-actions">
            <button className="ig-btn ig-btn-secondary" onClick={handleDiscard}>
              BACK
            </button>
            <button className="ig-btn ig-btn-primary" onClick={handleConfirmGenerate}>
              GENERATE IMAGE
            </button>
          </div>
        </div>
      )}

      {/* ─── Generating Stage ─── */}
      {stage === "generating" && (
        <div className="ig-loading">
          <div className="ig-spinner" />
          <p className="ig-loading-text">{progress}</p>
          <p className="ig-loading-sub">FLUX is creating your image</p>
          <button className="ig-btn ig-btn-ghost" onClick={handleDiscard}>
            CANCEL
          </button>
        </div>
      )}

      {/* ─── Result Modal ─── */}
      {stage === "done" && imageUrl && (
        <div className="ig-modal-overlay" onClick={handleDiscard}>
          <div className="ig-modal" onClick={(e) => e.stopPropagation()}>
            <div className="ig-modal-image-wrap">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={imageUrl} alt="Generated" className="ig-modal-image" />
            </div>

            <div className="ig-modal-prompt">{enhancedPrompt.slice(0, 120)}...</div>

            <div className="ig-modal-actions">
              <button className="ig-btn ig-btn-accept" onClick={handleAccept}>
                ACCEPT
              </button>
              <button className="ig-btn ig-btn-redo" onClick={handleRedo}>
                REDO
              </button>
              <button className="ig-btn ig-btn-discard" onClick={handleDiscard}>
                DISCARD
              </button>
            </div>

            <button className="ig-btn ig-btn-edit" onClick={handleEditPrompt}>
              EDIT PROMPT
            </button>
          </div>
        </div>
      )}

      <style jsx>{`
        .ig-container {
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          min-height: 400px;
          padding: 24px;
          width: 100%;
          max-width: 700px;
          margin: 0 auto;
        }

        .ig-title {
          font-size: 11px;
          letter-spacing: 4px;
          color: var(--accent, #40c8f0);
          opacity: 0.6;
          margin-bottom: 6px;
          text-align: center;
        }
        .ig-subtitle {
          font-size: 10px;
          color: rgba(255, 255, 255, 0.25);
          margin-bottom: 20px;
          text-align: center;
        }

        .ig-input-area {
          width: 100%;
          display: flex;
          flex-direction: column;
          align-items: center;
        }

        .ig-textarea {
          width: 100%;
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 6px;
          color: rgba(255, 255, 255, 0.8);
          font-size: 13px;
          padding: 14px;
          resize: vertical;
          outline: none;
          font-family: inherit;
          line-height: 1.5;
          transition: border-color 0.2s;
        }
        .ig-textarea:focus {
          border-color: var(--accent, #40c8f0);
        }
        .ig-textarea::placeholder {
          color: rgba(255, 255, 255, 0.15);
        }

        .ig-btn {
          font-size: 9px;
          letter-spacing: 3px;
          padding: 10px 28px;
          border: 1px solid transparent;
          border-radius: 4px;
          cursor: pointer;
          transition: all 0.2s;
          text-transform: uppercase;
          font-weight: 500;
          font-family: inherit;
        }
        .ig-btn:disabled {
          opacity: 0.3;
          cursor: not-allowed;
        }
        .ig-btn-primary {
          background: rgba(64, 200, 240, 0.1);
          border-color: rgba(64, 200, 240, 0.3);
          color: var(--accent, #40c8f0);
          margin-top: 16px;
        }
        .ig-btn-primary:hover:not(:disabled) {
          background: rgba(64, 200, 240, 0.2);
          border-color: var(--accent, #40c8f0);
        }
        .ig-btn-secondary {
          background: rgba(255, 255, 255, 0.03);
          border-color: rgba(255, 255, 255, 0.1);
          color: rgba(255, 255, 255, 0.4);
        }
        .ig-btn-secondary:hover {
          color: rgba(255, 255, 255, 0.7);
          border-color: rgba(255, 255, 255, 0.2);
        }
        .ig-btn-ghost {
          background: none;
          color: rgba(255, 255, 255, 0.25);
          margin-top: 16px;
        }
        .ig-btn-ghost:hover {
          color: rgba(255, 255, 255, 0.5);
        }

        .ig-btn-accept {
          background: rgba(64, 240, 128, 0.1);
          border-color: rgba(64, 240, 128, 0.4);
          color: #40f080;
        }
        .ig-btn-accept:hover {
          background: rgba(64, 240, 128, 0.2);
        }
        .ig-btn-redo {
          background: rgba(64, 160, 240, 0.1);
          border-color: rgba(64, 160, 240, 0.4);
          color: #40a0f0;
        }
        .ig-btn-redo:hover {
          background: rgba(64, 160, 240, 0.2);
        }
        .ig-btn-discard {
          background: rgba(240, 64, 64, 0.1);
          border-color: rgba(240, 64, 64, 0.3);
          color: #f04040;
        }
        .ig-btn-discard:hover {
          background: rgba(240, 64, 64, 0.2);
        }
        .ig-btn-edit {
          background: none;
          border: none;
          color: rgba(255, 255, 255, 0.2);
          font-size: 8px;
          letter-spacing: 2px;
          margin-top: 12px;
          padding: 4px 8px;
        }
        .ig-btn-edit:hover {
          color: var(--accent, #40c8f0);
        }

        .ig-error {
          margin-top: 16px;
          padding: 12px 16px;
          background: rgba(240, 64, 64, 0.08);
          border: 1px solid rgba(240, 64, 64, 0.2);
          border-radius: 4px;
          color: #f08080;
          font-size: 11px;
          width: 100%;
          display: flex;
          align-items: flex-start;
          gap: 8px;
        }
        .ig-error-icon {
          width: 16px;
          height: 16px;
          border-radius: 50%;
          background: rgba(240, 64, 64, 0.2);
          color: #f04040;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 10px;
          font-weight: bold;
          flex-shrink: 0;
        }

        .ig-loading {
          display: flex;
          flex-direction: column;
          align-items: center;
          gap: 12px;
          padding: 40px;
        }
        .ig-spinner {
          width: 32px;
          height: 32px;
          border: 2px solid rgba(255, 255, 255, 0.06);
          border-top-color: var(--accent, #40c8f0);
          border-radius: 50%;
          animation: ig-spin 0.8s linear infinite;
        }
        .ig-loading-text {
          font-size: 11px;
          color: rgba(255, 255, 255, 0.5);
          letter-spacing: 2px;
          text-transform: uppercase;
        }
        .ig-loading-sub {
          font-size: 9px;
          color: rgba(255, 255, 255, 0.2);
        }

        .ig-review {
          width: 100%;
        }
        .ig-review-title {
          font-size: 9px;
          letter-spacing: 3px;
          color: var(--accent, #40c8f0);
          opacity: 0.5;
          margin-bottom: 12px;
        }
        .ig-prompt-box {
          width: 100%;
          margin-bottom: 16px;
        }
        .ig-prompt-edit {
          width: 100%;
          background: rgba(255, 255, 255, 0.03);
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 6px;
          color: rgba(255, 255, 255, 0.7);
          font-size: 12px;
          padding: 14px;
          resize: vertical;
          outline: none;
          font-family: inherit;
          line-height: 1.6;
        }
        .ig-prompt-edit:focus {
          border-color: var(--accent, #40c8f0);
        }
        .ig-review-actions {
          display: flex;
          gap: 12px;
          justify-content: center;
        }

        .ig-modal-overlay {
          position: fixed;
          inset: 0;
          z-index: 200;
          background: rgba(0, 0, 0, 0.85);
          backdrop-filter: blur(8px);
          display: flex;
          align-items: center;
          justify-content: center;
          padding: 24px;
        }
        .ig-modal {
          display: flex;
          flex-direction: column;
          align-items: center;
          max-width: 900px;
          width: 100%;
        }
        .ig-modal-image-wrap {
          border: 1px solid rgba(255, 255, 255, 0.08);
          border-radius: 8px;
          overflow: hidden;
          box-shadow: 0 0 60px rgba(64, 200, 240, 0.08);
          max-height: 70vh;
        }
        .ig-modal-image {
          max-width: 100%;
          max-height: 70vh;
          object-fit: contain;
          display: block;
        }
        .ig-modal-prompt {
          font-size: 9px;
          color: rgba(255, 255, 255, 0.2);
          margin-top: 14px;
          text-align: center;
          max-width: 500px;
        }
        .ig-modal-actions {
          display: flex;
          gap: 14px;
          margin-top: 20px;
        }

        @keyframes ig-spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
