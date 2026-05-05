"""Auth and Streamable HTTP protocol tests.

Covers:
- Bearer token authentication (401/403)
- POST /sse — manifest, tools/list, initialize
- No-auth mode (backward compatible)
"""

from __future__ import annotations

import json
import os

import httpx
import pytest

# Streamable HTTP requires these Accept headers
STREAMABLE_HEADERS = {"Accept": "application/json, text/event-stream"}


class TestAuthMiddleware:
    """Token-based authentication tests."""

    def test_health_is_always_open(self, sandbox_server: str):
        """Health endpoint should not require auth, even with API_TOKEN set."""
        resp = httpx.get(f"{sandbox_server}/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_sse_without_token_200(self, sandbox_server: str):
        """Without API_TOKEN, SSE is open."""
        resp = httpx.post(f"{sandbox_server}/sse", json={}, headers=STREAMABLE_HEADERS)
        assert resp.status_code in (200, 202, 400)

    def test_sse_with_bad_token_403(self):
        """Server with API_TOKEN rejects bad Bearer tokens with 403."""
        import subprocess
        import time

        # Start server WITH auth
        port = self._find_free_port()
        env = os.environ.copy()
        env["APP_PORT"] = str(port)
        env["APP_HOST"] = "127.0.0.1"
        env["LOG_LEVEL"] = "ERROR"
        env["API_TOKEN"] = "secret-token-123"

        proc = subprocess.Popen(
            ["uv", "run", "python", "main.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        try:
            deadline = time.monotonic() + 10
            base = f"http://127.0.0.1:{port}"
            while time.monotonic() < deadline:
                try:
                    if httpx.get(f"{base}/health", timeout=1).status_code == 200:
                        break
                except httpx.ConnectError:
                    time.sleep(0.3)
            else:
                raise RuntimeError("Server not ready")

            h = {**STREAMABLE_HEADERS}

            # No token → 401
            resp = httpx.post(
                f"{base}/sse",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
                headers=h,
            )
            assert resp.status_code == 401, f"Expected 401, got {resp.status_code}: {resp.text}"

            # Bad token → 403
            h["Authorization"] = "Bearer wrong-token"
            resp = httpx.post(
                f"{base}/sse",
                json={"jsonrpc": "2.0", "method": "initialize", "id": 1},
                headers=h,
            )
            assert resp.status_code == 403, f"Expected 403, got {resp.status_code}: {resp.text}"

            # Good token → 200/202
            h["Authorization"] = "Bearer secret-token-123"
            resp = httpx.post(
                f"{base}/sse",
                json={
                    "jsonrpc": "2.0",
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-11-25",
                        "clientInfo": {"name": "test", "version": "1.0"},
                    },
                    "id": 1,
                },
                headers=h,
            )
            assert resp.status_code in (200, 202), (
                f"Expected 200/202, got {resp.status_code}: {resp.text}"
            )
        finally:
            proc.terminate()
            proc.wait()

    def _find_free_port(self) -> int:
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("", 0))
            return s.getsockname()[1]


class TestStreamableHttpProtocol:
    """Streamable HTTP 2025 protocol tests — manifest, tools, initialize."""

    def test_post_sse_returns_manifest_or_session(self, sandbox_server: str):
        """POST /sse with initialize request returns 200/202 with JSON."""
        resp = httpx.post(
            f"{sandbox_server}/sse",
            json={
                "jsonrpc": "2.0",
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "clientInfo": {"name": "test", "version": "1.0"},
                },
                "id": 1,
            },
            headers=STREAMABLE_HEADERS,
        )
        assert resp.status_code in (200, 202), f"Unexpected: {resp.status_code}"
        ct = resp.headers.get("content-type", "")
        # May be JSON or SSE
        assert "json" in ct or "event-stream" in ct

    def test_post_sse_missing_accept_header_406(self, sandbox_server: str):
        """POST without Accept header gets 406 Not Acceptable."""
        resp = httpx.post(f"{sandbox_server}/sse", json={"foo": "bar"})
        assert resp.status_code == 406

    def test_get_sse_with_accept(self, sandbox_server: str):
        """GET /sse with Accept: application/json returns 200 (may be SSE or error)."""
        with httpx.stream(
            "GET",
            f"{sandbox_server}/sse",
            timeout=5,
            headers={"Accept": "application/json, text/event-stream"},
        ) as resp:
            # Streamable HTTP GET may return 200 or 400; both valid test outcomes
            assert resp.status_code in (200, 400, 406)

    def test_delete_sse_session(self, sandbox_server: str):
        """DELETE /sse terminates a session (Streamable HTTP spec)."""
        resp = httpx.delete(f"{sandbox_server}/sse", headers=STREAMABLE_HEADERS)
        assert resp.status_code in (200, 400, 404)


class TestFullMCPRoundTrip:
    """End-to-end: initialize → list_tools → call_tool via Streamable HTTP."""

    @pytest.mark.asyncio
    async def test_initialize_and_list_tools(self, sandbox_server: str):
        """Full MCP session lifecycle."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            result = await session.initialize()
            # Accept both 2025-03-26 and 2025-11-25
            assert result.protocolVersion in ("2025-03-26", "2025-11-25")

            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            assert "execute_code" in tool_names

    @pytest.mark.asyncio
    async def test_execute_python_and_parse_result(self, sandbox_server: str):
        """Execute Python code and verify structured result."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()

            code = "import json; print(json.dumps({'result': 2 + 2}))"
            result = await session.call_tool(
                "execute_code",
                arguments={"language": "python", "code": code},
            )

            output = result.content[0].text if result.content else ""
            data = json.loads(output)
            assert data.get("exit_code") == 0
            stdout = json.loads(data.get("stdout", "{}"))
            assert stdout.get("result") == 4

    @pytest.mark.asyncio
    async def test_execute_multiple_languages(self, sandbox_server: str):
        """Execute Python, JS, Bash in sequence — session reuse."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()

            # Python
            r = await session.call_tool(
                "execute_code",
                arguments={"language": "python", "code": "print('py')"},
            )
            assert "py" in (r.content[0].text if r.content else "")

            # JS
            r = await session.call_tool(
                "execute_code",
                arguments={"language": "javascript", "code": "console.log('js')"},
            )
            assert "js" in (r.content[0].text if r.content else "")

            # Bash
            r = await session.call_tool(
                "execute_code",
                arguments={"language": "bash", "code": "echo bash"},
            )
            assert "bash" in (r.content[0].text if r.content else "")
