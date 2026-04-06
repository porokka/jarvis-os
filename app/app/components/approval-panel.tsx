"use client";

import { useState, useEffect, useCallback, useRef } from "react";

interface ApprovalRequest {
  id: string;
  tool: string;
  description: string;
  params: Record<string, unknown>;
  createdAt?: number;
}

const JARVIS_URL = process.env.NEXT_PUBLIC_JARVIS_URL || "https://localhost:3100";

const TOOL_ICONS: Record<string, string> = {
  shell_exec: "terminal",
  file_write: "file",
  git_commit: "git-commit",
  git_push: "git-push",
  vault_write: "vault",
  sync_vault: "sync",
  sync_code: "sync",
};

const TOOL_COLORS: Record<string, string> = {
  shell_exec: "border-yellow-500/40 bg-yellow-500/5",
  file_write: "border-blue-500/40 bg-blue-500/5",
  git_commit: "border-green-500/40 bg-green-500/5",
  git_push: "border-red-500/40 bg-red-500/5",
  vault_write: "border-purple-500/40 bg-purple-500/5",
  sync_vault: "border-cyan-500/40 bg-cyan-500/5",
  sync_code: "border-cyan-500/40 bg-cyan-500/5",
};

export function ApprovalPanel({
  onApprovalChange,
}: {
  onApprovalChange?: (count: number) => void;
}) {
  const [requests, setRequests] = useState<ApprovalRequest[]>([]);
  const [resolving, setResolving] = useState<Set<string>>(new Set());
  const eventSourceRef = useRef<EventSource | null>(null);

  // Connect to SSE stream for real-time approval requests
  useEffect(() => {
    const connect = () => {
      const es = new EventSource(`${JARVIS_URL}/approvals/stream`);

      es.addEventListener("approval_request", (e) => {
        const req: ApprovalRequest = JSON.parse(e.data);
        setRequests((prev) => {
          if (prev.some((r) => r.id === req.id)) return prev;
          return [...prev, req];
        });
      });

      es.addEventListener("approval_resolved", (e) => {
        const { id } = JSON.parse(e.data);
        setRequests((prev) => prev.filter((r) => r.id !== id));
        setResolving((prev) => {
          const next = new Set(prev);
          next.delete(id);
          return next;
        });
      });

      es.onerror = () => {
        es.close();
        // Reconnect after 3s
        setTimeout(connect, 3000);
      };

      eventSourceRef.current = es;
    };

    connect();

    // Also fetch any existing pending approvals
    fetch(`${JARVIS_URL}/approvals`)
      .then((r) => r.json())
      .then((pending: ApprovalRequest[]) => {
        if (Array.isArray(pending) && pending.length > 0) {
          setRequests(pending);
        }
      })
      .catch(() => {});

    return () => {
      eventSourceRef.current?.close();
    };
  }, []);

  // Notify parent of count changes
  useEffect(() => {
    onApprovalChange?.(requests.length);
  }, [requests.length, onApprovalChange]);

  const resolve = useCallback(async (id: string, approved: boolean) => {
    setResolving((prev) => new Set(prev).add(id));
    try {
      await fetch(`${JARVIS_URL}/approvals/${id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approved }),
      });
      setRequests((prev) => prev.filter((r) => r.id !== id));
    } catch {
      // Will retry on next click
    }
    setResolving((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }, []);

  if (requests.length === 0) return null;

  return (
    <div className="fixed top-16 right-6 z-50 flex flex-col gap-2 max-w-sm w-full">
      {requests.map((req) => {
        const isResolving = resolving.has(req.id);
        const colorClass = TOOL_COLORS[req.tool] || "border-white/20 bg-white/5";

        return (
          <div
            key={req.id}
            className={`rounded-lg border px-4 py-3 backdrop-blur-md ${colorClass} animate-slide-in`}
          >
            {/* Header */}
            <div className="flex items-center gap-2 mb-2">
              <div className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
              <span className="text-[10px] tracking-[2px] uppercase text-white/40">
                APPROVAL REQUIRED
              </span>
            </div>

            {/* Tool name */}
            <div className="text-sm font-medium text-white/90 mb-1">
              {req.tool.replace(/_/g, " ")}
            </div>

            {/* Description */}
            <p className="text-xs text-white/50 mb-3 leading-relaxed break-all">
              {req.description}
            </p>

            {/* Params preview */}
            {req.params && Object.keys(req.params).length > 0 && (
              <pre className="text-[10px] text-white/30 bg-black/30 rounded px-2 py-1 mb-3 overflow-x-auto max-h-20">
                {JSON.stringify(req.params, null, 2)}
              </pre>
            )}

            {/* Actions */}
            <div className="flex gap-2">
              <button
                onClick={() => resolve(req.id, true)}
                disabled={isResolving}
                className="flex-1 px-3 py-1.5 rounded text-xs font-medium tracking-wider uppercase
                  bg-green-500/20 border border-green-500/40 text-green-400
                  hover:bg-green-500/30 hover:border-green-500/60
                  disabled:opacity-30 transition-all"
              >
                {isResolving ? "..." : "APPROVE"}
              </button>
              <button
                onClick={() => resolve(req.id, false)}
                disabled={isResolving}
                className="flex-1 px-3 py-1.5 rounded text-xs font-medium tracking-wider uppercase
                  bg-red-500/20 border border-red-500/40 text-red-400
                  hover:bg-red-500/30 hover:border-red-500/60
                  disabled:opacity-30 transition-all"
              >
                {isResolving ? "..." : "DENY"}
              </button>
            </div>

            {/* Timer */}
            <ApprovalTimer createdAt={req.createdAt} />
          </div>
        );
      })}
    </div>
  );
}

function ApprovalTimer({ createdAt }: { createdAt?: number }) {
  const [elapsed, setElapsed] = useState(0);
  const start = createdAt || Date.now();

  useEffect(() => {
    const interval = setInterval(() => {
      setElapsed(Math.floor((Date.now() - start) / 1000));
    }, 1000);
    return () => clearInterval(interval);
  }, [start]);

  const remaining = Math.max(0, 120 - elapsed);
  const pct = (remaining / 120) * 100;

  return (
    <div className="mt-2">
      <div className="h-0.5 bg-white/5 rounded-full overflow-hidden">
        <div
          className="h-full bg-amber-400/40 transition-all duration-1000 ease-linear"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-[9px] text-white/20 mt-1 text-right">
        {remaining}s remaining
      </p>
    </div>
  );
}
