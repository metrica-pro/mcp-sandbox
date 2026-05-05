"""MCP Sandbox — lightweight code execution server.

Provides a single MCP tool ``execute_code`` that runs Python, JavaScript
or Bash code inside the current process (no Docker). Isolation is
expected to be enforced at the K8s pod level (securityContext, limits).
"""

import os
import subprocess
import tempfile

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP

from mcp_sandbox.api.routes import configure_app
from mcp_sandbox.utils.config import HOST, PORT, logger

# ── MCP server ───────────────────────────────────────────────────────────

mcp = FastMCP("Code Sandbox")

# Runtimes available inside the container image
RUNNERS = {
    "python": ["python3"],
    "javascript": ["node"],
    "bash": ["bash"],
}

SUFFIXES = {"python": ".py", "javascript": ".js", "bash": ".sh"}


@mcp.tool(
    name="execute_code",
    description=(
        "Execute Python, JavaScript or Bash code. Returns stdout, stderr and exit_code."
    ),
)
def execute_code(language: str, code: str) -> dict:
    """Run *code* in a subprocess and return the result."""
    if language not in RUNNERS:
        return {
            "error": (
                f"Unsupported language: {language}. Use one of: {list(RUNNERS.keys())}"
            )
        }

    tmp_file = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=SUFFIXES[language],
        delete=False,
    )
    try:
        tmp_file.write(code)
        tmp_file.flush()
        tmp_file.close()

        result = subprocess.run(
            RUNNERS[language] + [tmp_file.name],
            capture_output=True,
            text=True,
            timeout=30,
            cwd="/tmp",
            env={"HOME": "/tmp", "PATH": os.environ.get("PATH", "")},
        )
        return {
            "stdout": result.stdout[:10000],
            "stderr": result.stderr[:5000],
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Execution timeout after 30s"}
    finally:
        try:
            os.unlink(tmp_file.name)
        except OSError:
            pass


# ── FastAPI application ──────────────────────────────────────────────────

app = FastAPI(title="MCP Sandbox")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Wire up SSE transport and /health endpoint
configure_app(app, mcp._mcp_server)

logger.info("MCP Sandbox starting on %s:%s", HOST, PORT)


# ── Entry point ──────────────────────────────────────────────────────


def main():
    """Start the MCP Sandbox server."""
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
