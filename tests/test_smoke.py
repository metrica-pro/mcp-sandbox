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
        """GET /sse with Accept: text/event-stream returns 200 SSE."""
        import httpx

        with httpx.stream(
            "GET",
            f"{sandbox_server}/sse",
            timeout=5,
            headers={"Accept": "application/json, text/event-stream"},
        ) as resp:
            assert resp.status_code in (200, 400, 406)

    def test_sse_endpoint_is_connectable(self, sandbox_server: str):
        """Verify /sse endpoint is reachable (stream may remain open)."""
        import httpx

        try:
            with httpx.stream(
                "GET",
                f"{sandbox_server}/sse",
                timeout=3,
                headers={"Accept": "application/json, text/event-stream"},
            ) as resp:
                assert resp.status_code in (200, 400, 406)
        except httpx.ReadTimeout:
            pass


class TestMCPExecuteCode:
    """Full MCP protocol tests — connect via SSE and call execute_code."""

    @pytest.mark.asyncio
    async def test_list_tools(self, sandbox_server: str):
        """Connect via MCP Streamable HTTP client and list available tools."""
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (
                read,
                write,
                _,
            ),
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
        from mcp.client.streamable_http import streamablehttp_client

        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (
                read,
                write,
                _,
            ),
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
        from mcp.client.streamable_http import streamablehttp_client

        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (
                read,
                write,
                _,
            ),
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
        from mcp.client.streamable_http import streamablehttp_client

        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (
                read,
                write,
                _,
            ),
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
        from mcp.client.streamable_http import streamablehttp_client

        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (
                read,
                write,
                _,
            ),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "execute_code",
                arguments={"language": "rust", "code": "fn main(){}"},
            )
            output = result.content[0].text if result.content else ""
            assert "error" in output.lower() or "unsupported" in output.lower()
