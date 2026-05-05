"""Smoke tests — run against a live server started by the conftest fixture."""

from __future__ import annotations

import pytest


class TestHealthEndpoint:
    """Smoke tests for the /health liveness probe."""

    def test_health_returns_200(self, sandbox_server: str):
        import httpx

        resp = httpx.get(f"{sandbox_server}/health")
        assert resp.status_code == 200

    def test_health_returns_ok(self, sandbox_server: str):
        import httpx

        resp = httpx.get(f"{sandbox_server}/health")
        data = resp.json()
        assert data == {"status": "ok"}

    def test_health_is_json(self, sandbox_server: str):
        import httpx

        resp = httpx.get(f"{sandbox_server}/health")
        assert resp.headers.get("content-type", "").startswith("application/json")


class TestSSEEndpoint:
    """Smoke tests for the SSE endpoint."""

    def test_sse_accepts_connection(self, sandbox_server: str):
        """Verify /sse returns 200 with text/event-stream content type.

        SSE is a long-lived streaming connection; we use a stream
        request and read just the first chunk to verify headers.
        """
        import httpx

        with httpx.stream("GET", f"{sandbox_server}/sse", timeout=5) as resp:
            assert resp.status_code == 200
            assert resp.headers.get("content-type", "").startswith("text/event-stream")

    def test_sse_endpoint_is_connectable(self, sandbox_server: str):
        """Verify /sse endpoint is reachable (stream may remain open)."""
        import httpx

        try:
            with httpx.stream("GET", f"{sandbox_server}/sse", timeout=3) as resp:
                assert resp.status_code == 200
        except httpx.ReadTimeout:
            # SSE streams are long-lived; timeout is expected
            pass


class TestMCPExecuteCode:
    """Full MCP protocol tests — connect via SSE and call execute_code."""

    @pytest.mark.asyncio
    async def test_list_tools(self, sandbox_server: str):
        """Connect via MCP SSE client and list available tools."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        async with (
            sse_client(f"{sandbox_server}/sse") as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            assert "execute_code" in tool_names

    @pytest.mark.asyncio
    async def test_execute_python(self, sandbox_server: str):
        """Execute Python code via MCP protocol."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        async with (
            sse_client(f"{sandbox_server}/sse") as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "execute_code",
                arguments={"language": "python", "code": "print(2+2)"},
            )
            output = result.content[0].text if result.content else ""
            assert "4" in output

    @pytest.mark.asyncio
    async def test_execute_javascript(self, sandbox_server: str):
        """Execute JavaScript code via MCP protocol."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        async with (
            sse_client(f"{sandbox_server}/sse") as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "execute_code",
                arguments={"language": "javascript", "code": "console.log(6*7)"},
            )
            output = result.content[0].text if result.content else ""
            assert "42" in output

    @pytest.mark.asyncio
    async def test_execute_bash(self, sandbox_server: str):
        """Execute Bash code via MCP protocol."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        async with (
            sse_client(f"{sandbox_server}/sse") as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "execute_code",
                arguments={"language": "bash", "code": "echo hello_from_bash"},
            )
            output = result.content[0].text if result.content else ""
            assert "hello_from_bash" in output

    @pytest.mark.asyncio
    async def test_execute_unsupported_language(self, sandbox_server: str):
        """Unsupported language should return an error via MCP."""
        from mcp import ClientSession
        from mcp.client.sse import sse_client

        async with (
            sse_client(f"{sandbox_server}/sse") as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "execute_code",
                arguments={"language": "rust", "code": "fn main(){}"},
            )
            output = result.content[0].text if result.content else ""
            assert "error" in output.lower() or "unsupported" in output.lower()
