"""Package entry point for the MCP Sandbox server.

This module is referenced by the ``[project.scripts]`` console_script
so that ``mcp-sandbox`` works regardless of the working directory.
"""

from __future__ import annotations


def main() -> None:
    """Start the MCP Sandbox server."""
    import uvicorn

    # Deferred imports avoid circular import issues at module load time
    from main import app
    from mcp_sandbox.utils.config import HOST, PORT

    uvicorn.run(app, host=HOST, port=PORT, limit_concurrency=50)
