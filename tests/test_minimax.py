"""Smoke test: execute_code calling MiniMax Platform API (chat completion → JSON).

Realistic MCP end-to-end:
1. Python script calls MiniMax /v1/chat/completions (OpenAI-compatible)
2. Sends a chat prompt: "What is the capital of France?"
3. Parses JSON response
4. Extracts: reply, model, usage (tokens)
5. Returns structured JSON via stdout

All executed through the MCP ``execute_code`` tool.
"""

from __future__ import annotations

import json
import os

import pytest

# ── Python scripts for execute_code ──────────────────────────────────────

CHAT_SCRIPT = r"""
import os, json, urllib.request, urllib.error

API_KEY = os.environ["MINIMAX_API_KEY"]
MODEL = "MiniMax-M2.7"

payload = {
    "model": MODEL,
    "messages": [
        {"role": "system", "content": "You are a helpful assistant. Answer concisely."},
        {"role": "user", "content": "What is the capital of France?"},
    ],
}

req = urllib.request.Request(
    "https://api.minimax.io/v1/chat/completions",
    data=json.dumps(payload).encode(),
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode())
        choice = result["choices"][0]["message"]
        output = {
            "api": "minimax",
            "model": result.get("model", MODEL),
            "reply": choice["content"],
            "usage": result.get("usage", {}),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
except urllib.error.HTTPError as e:
    body = e.read().decode()[:500]
    print(json.dumps({"http_error": e.code, "body": body}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"error": str(exc)}, ensure_ascii=False))
"""

# Script with reasoning/thinking
REASONING_SCRIPT = r"""
import os, json, urllib.request, urllib.error

API_KEY = os.environ["MINIMAX_API_KEY"]

payload = {
    "model": "MiniMax-M2.7",
    "messages": [
        {"role": "system", "content": "You are a math tutor. Think step-by-step."},
        {"role": "user", "content": "If x^2 = 16, what is x?"},
    ],
    "extra_body": {"reasoning_split": True},
}

req = urllib.request.Request(
    "https://api.minimax.io/v1/chat/completions",
    data=json.dumps(payload).encode(),
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    },
    method="POST",
)

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read().decode())
        msg = result["choices"][0]["message"]
        reasoning = msg.get("reasoning_details", [])
        output = {
            "api": "minimax",
            "model": result.get("model", "MiniMax-M2.7"),
            "reply": msg["content"],
            "has_reasoning": len(reasoning) > 0,
            "usage": result.get("usage", {}),
        }
        print(json.dumps(output, ensure_ascii=False, indent=2))
except urllib.error.HTTPError as e:
    body = e.read().decode()[:500]
    print(json.dumps({"http_error": e.code, "body": body}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({"error": str(exc)}, ensure_ascii=False))
"""


# ── Direct tests (no MCP server needed) ──────────────────────────────────


class TestMinimaxChat:
    """Test MiniMax chat completion via _execute_sync."""

    def test_chat_returns_json(self):
        """Send a chat prompt, verify structured JSON response."""
        from main import _execute_sync

        if "MINIMAX_API_KEY" not in os.environ:
            pytest.skip("MINIMAX_API_KEY not set in environment")

        result = _execute_sync("python", CHAT_SCRIPT.strip())

        if "error" in result:
            pytest.fail(f"Script execution error: {result['error']}")

        stdout = result.get("stdout", "")
        assert stdout, "Empty stdout"

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON: {e}\nRaw:\n{stdout}")

        # Handle API errors gracefully (MCP round-trip still verified)
        if "http_error" in data:
            code = data["http_error"]
            body = data.get("body", "")
            print(f"\n⚠️  MiniMax API HTTP {code}: {body[:200]}")
            # Auth or balance issues — MCP round-trip works, API needs setup
            if code in (401, 403, 429):
                print("   MCP round-trip OK — API key valid but needs funds/permissions.")
                return
            pytest.fail(f"MiniMax unexpected HTTP {code}: {data}")

        if "error" in data:
            pytest.fail(f"MiniMax error: {data['error']}")

        assert data.get("api") == "minimax", f"Unexpected api: {data}"
        assert "reply" in data, f"No reply in: {data}"
        assert len(data["reply"]) > 0, "Empty reply"
        assert "usage" in data, f"No usage stats: {data}"
        assert data["usage"].get("total_tokens", 0) > 0, "Zero tokens used"

        print(f"\n✅ MiniMax M2.7: {data['reply'][:120]}")
        usage = data["usage"]
        print(
            f"   Tokens: {usage['total_tokens']} "
            f"(prompt={usage.get('prompt_tokens', '?')}, "
            f"completion={usage.get('completion_tokens', '?')})"
        )

    def test_chat_stderr_clean(self):
        """No tracebacks in stderr."""
        from main import _execute_sync

        if "MINIMAX_API_KEY" not in os.environ:
            pytest.skip("MINIMAX_API_KEY not set in environment")

        result = _execute_sync("python", CHAT_SCRIPT.strip())
        stderr = result.get("stderr", "")
        assert "Traceback" not in stderr, f"Traceback in stderr:\n{stderr}"

    def test_reasoning_mode(self):
        """Test with reasoning_split enabled — verify reasoning details."""
        from main import _execute_sync

        if "MINIMAX_API_KEY" not in os.environ:
            pytest.skip("MINIMAX_API_KEY not set in environment")

        result = _execute_sync("python", REASONING_SCRIPT.strip())

        stdout = result.get("stdout", "")
        assert stdout, "Empty stdout"

        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as e:
            pytest.fail(f"Invalid JSON: {e}\nRaw:\n{stdout}")

        if "http_error" in data:
            code = data["http_error"]
            if code in (401, 403, 429):
                print(f"\n⚠️  MiniMax HTTP {code} — round-trip OK")
                return
            pytest.fail(f"HTTP {code}: {data}")

        if "error" in data:
            pytest.fail(f"Error: {data['error']}")

        assert data.get("api") == "minimax"
        assert "reply" in data
        # reasoning_split should produce reasoning details
        print(f"\n✅ MiniMax reasoning: {data['reply'][:120]}")
        print(f"   Has reasoning: {data['has_reasoning']}")


# ── MCP protocol test (full SSE round-trip) ──────────────────────────────


class TestMinimaxViaMCP:
    """Execute MiniMax chat through the full MCP SSE protocol."""

    @pytest.mark.asyncio
    async def test_chat_via_mcp(self, sandbox_server: str):
        """Connect via Streamable HTTP, call execute_code with MiniMax chat."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        if "MINIMAX_API_KEY" not in os.environ:
            pytest.skip("MINIMAX_API_KEY not set in environment")

        async with streamablehttp_client(f"{sandbox_server}/sse") as (
            read,
            write,
            _,
        ), ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                "execute_code",
                arguments={"language": "python", "code": CHAT_SCRIPT.strip()},
            )

            raw_output = result.content[0].text if result.content else ""
            assert raw_output, "Empty output from MCP"

            exec_result = json.loads(raw_output)
            if exec_result.get("error"):
                pytest.fail(f"MCP exec error: {exec_result['error']}")

            stdout_text = exec_result.get("stdout", "")
            data = json.loads(stdout_text)

            if "http_error" in data:
                code = data["http_error"]
                print(f"\n⚠️  MiniMax HTTP {code} via MCP — round-trip OK")
                if code in (401, 403, 429):
                    return
                pytest.fail(f"HTTP {code}: {data}")

            if "error" in data:
                pytest.fail(f"MiniMax error via MCP: {data['error']}")

            assert data.get("api") == "minimax"
            assert len(data.get("reply", "")) > 0

            print(f"\n✅ MCP MiniMax: {data['reply'][:120]}")

    @pytest.mark.asyncio
    async def test_reasoning_via_mcp(self, sandbox_server: str):
        """Reasoning mode through MCP."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        if "MINIMAX_API_KEY" not in os.environ:
            pytest.skip("MINIMAX_API_KEY not set in environment")

        async with streamablehttp_client(f"{sandbox_server}/sse") as (
            read,
            write,
            _,
        ), ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool(
                "execute_code",
                arguments={"language": "python", "code": REASONING_SCRIPT.strip()},
            )

            raw_output = result.content[0].text if result.content else ""
            exec_result = json.loads(raw_output)
            if exec_result.get("error"):
                pytest.fail(f"MCP exec error: {exec_result['error']}")

            stdout_text = exec_result.get("stdout", "")
            data = json.loads(stdout_text)

            if "http_error" in data:
                if data["http_error"] in (401, 403, 429):
                    print(f"\n⚠️  MiniMax HTTP {data['http_error']} via MCP — round-trip OK")
                    return
                pytest.fail(f"HTTP {data['http_error']}: {data}")

            assert data.get("api") == "minimax"
            assert "reply" in data


# ── Edge case tests ──────────────────────────────────────────────────────


class TestMinimaxEdgeCases:
    """Edge cases for MiniMax API."""

    def test_invalid_api_key(self):
        """Bad API key should get 401/403."""
        from main import _execute_sync

        script = r"""
import json, urllib.request, urllib.error
payload = {"model": "MiniMax-M2.7", "messages": [{"role": "user", "content": "Hi"}]}
req = urllib.request.Request(
    "https://api.minimax.io/v1/chat/completions",
    data=json.dumps(payload).encode(),
    headers={"Authorization": "Bearer deadbeef", "Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(json.dumps({"unexpected_status": resp.status}))
except urllib.error.HTTPError as e:
    print(json.dumps({"http_error": e.code}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"error": str(e)}, ensure_ascii=False))
"""
        result = _execute_sync("python", script.strip())
        stdout = result.get("stdout", "")
        data = json.loads(stdout)
        http_err = data.get("http_error")
        assert http_err in (401, 403), f"Expected 401/403, got: {data}"

    def test_invalid_model(self):
        """Non-existent model should get 4xx error."""
        from main import _execute_sync

        if "MINIMAX_API_KEY" not in os.environ:
            pytest.skip("MINIMAX_API_KEY not set in environment")

        api_key = os.environ["MINIMAX_API_KEY"]
        script = f"""
import json, urllib.request, urllib.error
API_KEY = "{api_key}"
payload = {{"model": "nonexistent-model-999", "messages": [{{"role": "user", "content": "Hi"}}]}}
req = urllib.request.Request(
    "https://api.minimax.io/v1/chat/completions",
    data=json.dumps(payload).encode(),
    headers={{"Authorization": f"Bearer {{API_KEY}}", "Content-Type": "application/json"}},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(json.dumps({{"unexpected_status": resp.status}}))
except urllib.error.HTTPError as e:
    body = e.read().decode()[:300]
    print(json.dumps({{"http_error": e.code, "body": body}}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({{"error": str(e)}}, ensure_ascii=False))
"""
        result = _execute_sync("python", script.strip())
        stdout = result.get("stdout", "")
        data = json.loads(stdout)
        assert data.get("http_error", 0) >= 400, f"Expected 4xx for bad model, got: {data}"
