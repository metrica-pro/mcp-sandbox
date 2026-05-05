"""Quick integration test: connect to the MCP server via SSE and call execute_code."""

import asyncio

from mcp import ClientSession
from mcp.client.sse import sse_client


async def main():
    print("Connecting to MCP server at http://localhost:8181/sse ...")

    async with (
        sse_client("http://localhost:8181/sse") as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        print("Connected!\n")

        # 1. List available tools
        tools = await session.list_tools()
        print("=== Available tools ===")
        for t in tools.tools:
            print(f"  • {t.name}: {t.description}")
        print()

        # 2. Execute Python code
        print("=== execute_code(language='python', code='print(2+2)') ===")
        result = await session.call_tool(
            "execute_code",
            arguments={"language": "python", "code": "print(2+2)"},
        )
        for c in result.content:
            print(c.text)
        print()

        # 3. Execute JavaScript code
        print("=== execute_code(language='javascript', code='console.log(6*7)') ===")
        result = await session.call_tool(
            "execute_code",
            arguments={"language": "javascript", "code": "console.log(6*7)"},
        )
        for c in result.content:
            print(c.text)
        print()

        # 4. Execute Bash code
        print("=== execute_code(language='bash', code='echo hello from bash') ===")
        result = await session.call_tool(
            "execute_code",
            arguments={"language": "bash", "code": "echo hello from bash"},
        )
        for c in result.content:
            print(c.text)
        print()

        # 5. Factorial test (the example from the spec)
        label = "=== execute_code(python, factorial(10)) ==="
        print(label)
        result = await session.call_tool(
            "execute_code",
            arguments={
                "language": "python",
                "code": "import math; print(math.factorial(10))",
            },
        )
        for c in result.content:
            print(c.text)
        print()

        # 6. Unsupported language
        print("=== execute_code(language='rust', code='fn main(){}') ===")
        result = await session.call_tool(
            "execute_code",
            arguments={"language": "rust", "code": "fn main(){}"},
        )
        for c in result.content:
            print(c.text)
        print()

        print("All tests passed!")


if __name__ == "__main__":
    asyncio.run(main())
