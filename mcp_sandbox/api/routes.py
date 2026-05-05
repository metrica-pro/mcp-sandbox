"""Simplified routes: SSE endpoint + health check.

This module provides ``configure_app`` which wires up the MCP SSE
transport and a /health liveness probe onto an existing FastAPI app.
"""

from fastapi import FastAPI, Request, Response
from mcp.server.sse import SseServerTransport

from mcp_sandbox.utils.config import logger


def configure_app(app: FastAPI, mcp_server) -> SseServerTransport:
    """Attach SSE and health routes to *app*.

    Parameters
    ----------
    app:
        A FastAPI application instance.
    mcp_server:
        The low-level ``mcp.server.Server`` object (``FastMCP._mcp_server``).

    Returns
    -------
    SseServerTransport
        The SSE transport so the caller can mount ``/messages/`` afterwards.
    """

    # Server-Sent Events transport
    event_stream = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> Response:
        """Handle an SSE connection from an MCP client."""
        logger.info("SSE connection opened from %s", request.client)
        async with event_stream.connect_sse(
            request.scope,
            request.receive,
            request._send,  # noqa: SLF001
        ) as (read_stream, write_stream):
            await mcp_server.run(
                read_stream,
                write_stream,
                mcp_server.create_initialization_options(),
            )
        return Response()

    app.add_route("/sse", handle_sse)
    app.mount("/messages/", app=event_stream.handle_post_message)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return event_stream
