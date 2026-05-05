"""Simplified routes: SSE endpoint + health check.

This module provides ``configure_app`` which wires up the MCP SSE
transport and a /health liveness probe onto an existing FastAPI app.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, Response
from mcp.server.sse import SseServerTransport

from mcp_sandbox.utils.config import logger


def _get_asgi_send(request: Request) -> Any:
    """Extract the ASGI send callable from a Starlette/FastAPI Request.

    Accessing ``request._send`` is a known workaround for the MCP SSE
    transport which expects raw ASGI primitives.  The underscore prefix
    denotes a private API — if Starlette changes this, the guard below
    will surface the problem at runtime instead of failing silently.
    """
    send: Any = getattr(request, "_send", None)
    if send is None:
        raise RuntimeError(
            "Cannot extract ASGI send callable from Request. "
            "The Starlette API may have changed — the SSE transport "
            "needs to be updated accordingly."
        )
    return send


def configure_app(app: FastAPI, mcp_server: Any) -> None:
    """Attach SSE and health routes to *app*.

    Parameters
    ----------
    app:
        A FastAPI application instance.
    mcp_server:
        The low-level ``mcp.server.Server`` object (``FastMCP._mcp_server``).
    """
    # Server-Sent Events transport
    event_stream = SseServerTransport("/messages/")

    async def handle_sse(request: Request) -> Response:
        """Handle an SSE connection from an MCP client."""
        logger.info("SSE connection opened from %s", request.client)
        async with event_stream.connect_sse(
            request.scope,
            request.receive,
            _get_asgi_send(request),
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
    async def health() -> dict[str, str]:
        return {"status": "ok"}
