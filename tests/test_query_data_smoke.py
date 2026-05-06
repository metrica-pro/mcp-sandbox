"""MCP protocol smoke tests for query_data tool — live server via conftest."""

from __future__ import annotations

import asyncio
import json

import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


class TestListTools:
    @pytest.mark.asyncio
    async def test_list_tools_includes_query_data(self, sandbox_server: str) -> None:
        """query_data appears alongside execute_code in tool list."""
        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            assert "execute_code" in tool_names
            assert "query_data" in tool_names


class TestQueryDataBasic:
    @pytest.mark.asyncio
    async def test_query_data_via_mcp_csv(self, sandbox_server: str) -> None:
        """Query CSV data through full MCP protocol."""
        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "query_data",
                arguments={
                    "sql": "SELECT * FROM input_data",
                    "data": "name,age\nAlice,30\nBob,25",
                    "data_format": "csv",
                },
            )
            output = result.content[0].text if result.content else ""
            assert "Alice" in output
            assert "Bob" in output

    @pytest.mark.asyncio
    async def test_query_data_via_mcp_json(self, sandbox_server: str) -> None:
        """Query JSON data through MCP."""
        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "query_data",
                arguments={
                    "sql": "SELECT * FROM input_data",
                    "data": '[{"x":1},{"x":2}]',
                    "data_format": "json",
                },
            )
            output = result.content[0].text if result.content else ""
            assert "1" in output and "2" in output

    @pytest.mark.asyncio
    async def test_query_data_via_mcp_no_data(self, sandbox_server: str) -> None:
        """Query without data — pure SELECT."""
        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "query_data",
                arguments={"sql": "SELECT 1+1 AS result"},
            )
            output = result.content[0].text if result.content else ""
            assert "2" in output

    @pytest.mark.asyncio
    async def test_query_data_via_mcp_error(self, sandbox_server: str) -> None:
        """Non-SELECT SQL returns error via MCP."""
        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "query_data",
                arguments={"sql": "INSERT INTO t VALUES (1)"},
            )
            output = result.content[0].text if result.content else ""
            assert "error" in output.lower()


class TestCrossTool:
    @pytest.mark.asyncio
    async def test_cross_tool_execute_then_query(self, sandbox_server: str) -> None:
        """Generate CSV via execute_code, then query with query_data."""
        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()

            # Generate CSV via Python
            exec_result = await session.call_tool(
                "execute_code",
                arguments={
                    "language": "python",
                    "code": "print('product,price\\napple,1.5\\nbanana,0.8')",
                },
            )
            exec_text = exec_result.content[0].text if exec_result.content else ""
            # Parse JSON ExecutionResult to extract stdout
            try:
                exec_data = json.loads(exec_text)
                csv_data = exec_data.get("stdout", "").strip()
            except (json.JSONDecodeError, AttributeError):
                csv_data = exec_text.strip()

            # Query generated CSV
            query_result = await session.call_tool(
                "query_data",
                arguments={
                    "sql": "SELECT COUNT(*) as cnt FROM input_data",
                    "data": csv_data,
                    "data_format": "csv",
                },
            )
            query_text = query_result.content[0].text if query_result.content else ""
            assert "2" in query_text  # 2 products

    @pytest.mark.asyncio
    async def test_query_then_execute_cross(self, sandbox_server: str) -> None:
        """Aggregate via query_data, then process via execute_code."""
        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()

            # First, aggregate via query_data
            query_result = await session.call_tool(
                "query_data",
                arguments={
                    "sql": "SELECT AVG(CAST(price AS DOUBLE)) as avg_price FROM input_data",
                    "data": "item,price\na,10\nb,20\nc,30",
                    "data_format": "csv",
                },
            )
            query_text = query_result.content[0].text if query_result.content else ""
            assert "20" in query_text  # avg is 20.0

            # Then, use the result in Python
            exec_result = await session.call_tool(
                "execute_code",
                arguments={
                    "language": "python",
                    "code": f"print('Aggregated result processed: {20.0 * 2}')",
                },
            )
            exec_text = exec_result.content[0].text if exec_result.content else ""
            assert "40" in exec_text


class TestComplexIntegration:
    @pytest.mark.asyncio
    async def test_large_csv_1000_rows(self, sandbox_server: str) -> None:
        """Large CSV with GROUP BY + ORDER BY + LIMIT."""
        # Build 1000-row CSV
        rows = ["id,value"] + [f"{i},{i * 2}" for i in range(1000)]
        csv_data = "\n".join(rows)

        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "query_data",
                arguments={
                    "sql": (
                        "SELECT CAST(value AS INTEGER) % 10 as grp, COUNT(*) as cnt "
                        "FROM input_data GROUP BY grp ORDER BY grp LIMIT 5"
                    ),
                    "data": csv_data,
                    "data_format": "csv",
                },
            )
            output = result.content[0].text if result.content else ""
            # Each group should have 200 rows (even values: 0,2,4,...)
            assert "200" in output

    @pytest.mark.asyncio
    async def test_unicode_data(self, sandbox_server: str) -> None:
        """CSV/JSON with Unicode, emoji, CJK preserved."""
        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()

            # Unicode CSV
            result = await session.call_tool(
                "query_data",
                arguments={
                    "sql": "SELECT * FROM input_data",
                    "data": "имя,эмодзи\nАлиса,😀\nБоб,🚀\n太郎,🍣",
                    "data_format": "csv",
                },
            )
            output = result.content[0].text if result.content else ""
            assert "Алиса" in output
            assert "😀" in output
            assert "太郎" in output

    @pytest.mark.asyncio
    async def test_sequential_queries_isolation(self, sandbox_server: str) -> None:
        """Five sequential queries with different data — each :memory: isolated."""
        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()

            for i in range(5):
                result = await session.call_tool(
                    "query_data",
                    arguments={
                        "sql": "SELECT COUNT(*) as cnt FROM input_data",
                        "data": f"col\n{i}",
                        "data_format": "csv",
                    },
                )
                output = result.content[0].text if result.content else ""
                assert "1" in output  # Each has exactly 1 row

    @pytest.mark.asyncio
    async def test_concurrent_mcp_queries(self, sandbox_server: str) -> None:
        """Three parallel MCP calls via asyncio.gather — no races."""

        async def single_query(i: int) -> str:
            async with (
                streamablehttp_client(f"{sandbox_server}/sse") as (read, write, _),
                ClientSession(read, write) as session,
            ):
                await session.initialize()
                result = await session.call_tool(
                    "query_data",
                    arguments={"sql": f"SELECT {i} AS val"},
                )
                return result.content[0].text if result.content else ""

        results = await asyncio.gather(
            single_query(1),
            single_query(2),
            single_query(3),
        )
        for i, r in enumerate(results, 1):
            assert str(i) in r

    @pytest.mark.asyncio
    async def test_error_propagation_mcp(self, sandbox_server: str) -> None:
        """SQL syntax error returns error in content, not HTTP 500."""
        async with (
            streamablehttp_client(f"{sandbox_server}/sse") as (read, write, _),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "query_data",
                arguments={"sql": "SELEC * FROM nonexistent"},
            )
            output = result.content[0].text if result.content else ""
            assert "error" in output.lower()
