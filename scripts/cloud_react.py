"""
Cloud ReAct — Tool-augmented cloud LLM calls.

Same ReAct loop as react_server.py but for cloud APIs.
Loads JARVIS skills and exposes them as tool definitions
in Claude/OpenAI format.

Usage:
  python3 cloud_react.py --provider anthropic --prompt "play radio nova"
  python3 cloud_react.py --provider openai --prompt "what devices are on the network?"
"""

import json
import sys
import os
import urllib.request
import urllib.error
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from skills.loader import load_skills, get_all_tools, get_all_tool_map

CONFIG_FILE = PROJECT_ROOT / "config" / "cloud_llm.json"
MAX_ITERATIONS = 5

# Provider configs
PROVIDERS = {
    "anthropic": {
        "url": "https://api.anthropic.com/v1/messages",
        "default_model": "claude-sonnet-4-20250514",
    },
    "openai": {
        "url": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o",
    },
    "groq": {
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "default_model": "llama-3.3-70b-versatile",
    },
}


def load_config():
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def ollama_tools_to_anthropic(tools: list) -> list:
    """Convert Ollama tool format to Anthropic tool format."""
    result = []
    for t in tools:
        fn = t.get("function", {})
        result.append({
            "name": fn["name"],
            "description": fn.get("description", ""),
            "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
        })
    return result


def ollama_tools_to_openai(tools: list) -> list:
    """Convert Ollama tool format to OpenAI tool format."""
    result = []
    for t in tools:
        fn = t.get("function", {})
        result.append({
            "type": "function",
            "function": {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            },
        })
    return result


def call_anthropic(api_key: str, model: str, system: str, messages: list, tools: list) -> dict:
    """Call Anthropic API with tools."""
    body = {
        "model": model,
        "max_tokens": 1000,
        "system": system,
        "messages": messages,
        "tools": ollama_tools_to_anthropic(tools),
    }

    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        PROVIDERS["anthropic"]["url"],
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_openai_compat(url: str, api_key: str, model: str, messages: list, tools: list) -> dict:
    """Call OpenAI-compatible API with tools."""
    body = {
        "model": model,
        "messages": messages,
        "tools": ollama_tools_to_openai(tools),
        "max_tokens": 1000,
    }

    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )

    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def react_loop_anthropic(api_key: str, model: str, system: str, prompt: str, tools: list, tool_map: dict) -> str:
    """ReAct loop for Anthropic Claude API."""
    messages = [{"role": "user", "content": prompt}]

    for iteration in range(MAX_ITERATIONS):
        data = call_anthropic(api_key, model, system, messages, tools)

        # Check for tool use
        content = data.get("content", [])
        stop_reason = data.get("stop_reason", "")

        if stop_reason != "tool_use":
            # Final text response
            text_parts = [c["text"] for c in content if c.get("type") == "text"]
            return " ".join(text_parts) if text_parts else ""

        # Execute tool calls
        messages.append({"role": "assistant", "content": content})

        tool_results = []
        for block in content:
            if block.get("type") == "tool_use":
                fn_name = block["name"]
                fn_args = block.get("input", {})
                executor = tool_map.get(fn_name)

                print(f"[CLOUD] Tool: {fn_name}({json.dumps(fn_args)[:80]})", file=sys.stderr)

                if executor:
                    try:
                        result = executor(**fn_args)
                    except Exception as e:
                        result = f"Tool error: {e}"
                else:
                    result = f"Unknown tool: {fn_name}"

                print(f"[CLOUD] Result: {result[:150]}", file=sys.stderr)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": str(result),
                })

        messages.append({"role": "user", "content": tool_results})

    return "Max iterations reached."


def react_loop_openai(url: str, api_key: str, model: str, system: str, prompt: str, tools: list, tool_map: dict) -> str:
    """ReAct loop for OpenAI-compatible APIs."""
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    for iteration in range(MAX_ITERATIONS):
        data = call_openai_compat(url, api_key, model, messages, tools)

        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        finish = choice.get("finish_reason", "")

        if finish != "tool_calls" or not msg.get("tool_calls"):
            return msg.get("content", "")

        # Execute tool calls
        messages.append(msg)

        for tc in msg["tool_calls"]:
            fn_name = tc["function"]["name"]
            fn_args = json.loads(tc["function"].get("arguments", "{}"))
            executor = tool_map.get(fn_name)

            print(f"[CLOUD] Tool: {fn_name}({json.dumps(fn_args)[:80]})", file=sys.stderr)

            if executor:
                try:
                    result = executor(**fn_args)
                except Exception as e:
                    result = f"Tool error: {e}"
            else:
                result = f"Unknown tool: {fn_name}"

            print(f"[CLOUD] Result: {result[:150]}", file=sys.stderr)

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": str(result),
            })

    return "Max iterations reached."


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="anthropic")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--system", default="You are JARVIS, a helpful AI assistant. Use tools when needed. Keep responses concise, under 3 sentences. Plain text only.")
    parser.add_argument("--model", default="")
    args = parser.parse_args()

    # Load config
    cfg = load_config()
    provider_cfg = cfg.get(args.provider, {})
    api_key = provider_cfg.get("api_key", "")

    if not api_key:
        print(f"No API key for {args.provider} in config/cloud_llm.json", file=sys.stderr)
        sys.exit(1)

    model = args.model or provider_cfg.get("model") or PROVIDERS.get(args.provider, {}).get("default_model", "")

    # Load skills
    load_skills()
    tools = get_all_tools()
    tool_map = get_all_tool_map()

    print(f"[CLOUD] {args.provider} ({model}) with {len(tools)} tools", file=sys.stderr)

    # Run ReAct loop
    try:
        if args.provider == "anthropic":
            result = react_loop_anthropic(api_key, model, args.system, args.prompt, tools, tool_map)
        else:
            url = PROVIDERS.get(args.provider, {}).get("url", "")
            if not url:
                print(f"Unknown provider: {args.provider}", file=sys.stderr)
                sys.exit(1)
            result = react_loop_openai(url, api_key, model, args.system, args.prompt, tools, tool_map)

        print(result)

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        print(f"API error {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
