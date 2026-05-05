"""MCP Sandbox — lightweight code execution server.

Provides a single MCP tool ``execute_code`` that runs Python, JavaScript
or Bash code inside the current process (no Docker). Isolation is
expected to be enforced at the K8s pod level (securityContext, limits).
"""

import asyncio
import contextlib
import os
import shutil
import subprocess
import tempfile
from typing import TypedDict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP

from mcp_sandbox.api.routes import configure_app
from mcp_sandbox.utils.config import HOST, PORT, logger

# ── Constants ────────────────────────────────────────────────────────────

# Runtimes available inside the container image
RUNNERS: dict[str, list[str]] = {
    "python": ["python3"],
    "javascript": ["node"],
    "bash": ["bash"],
}

SUFFIXES: dict[str, str] = {"python": ".py", "javascript": ".js", "bash": ".sh"}

# Maximum code size (1 MB)
MAX_CODE_LENGTH: int = 1_000_000

# Maximum concurrent executions
MAX_CONCURRENT_EXECUTIONS: int = 10

# Safe environment variables to pass through to subprocess
SAFE_ENV_VARS: set[str] = {
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "PYTHONUNBUFFERED",
    "PYTHONIOENCODING",
    "TMPDIR",
    "TEMP",
    "USER",
    "LOGNAME",
}


# ── Type definitions ─────────────────────────────────────────────────────


class ExecutionResult(TypedDict, total=False):
    """Result from execute_code tool."""

    stdout: str
    stderr: str
    exit_code: int
    error: str


# ── MCP server ───────────────────────────────────────────────────────────

mcp = FastMCP("Code Sandbox")

# Semaphore to limit concurrent executions
_execution_semaphore = asyncio.Semaphore(MAX_CONCURRENT_EXECUTIONS)


def _build_env() -> dict[str, str]:
    """Build a safe environment dict for the subprocess."""
    env = {k: os.environ[k] for k in SAFE_ENV_VARS if k in os.environ}
    env.setdefault("HOME", "/tmp")
    return env


def _validate_input(language_raw: object, code_raw: object) -> ExecutionResult | None:
    """Validate execute_code inputs. Returns an error result or None if valid."""
    if not isinstance(language_raw, str) or not isinstance(code_raw, str):
        return ExecutionResult(error="Both 'language' and 'code' must be strings")

    language = language_raw.strip().lower()
    code = code_raw.strip()

    if not code:
        return ExecutionResult(error="Code must not be empty")

    if len(code) > MAX_CODE_LENGTH:
        return ExecutionResult(error=f"Code exceeds maximum size of {MAX_CODE_LENGTH:,} characters")

    if language not in RUNNERS:
        return ExecutionResult(
            error=f"Unsupported language: '{language}'. Use one of: {sorted(RUNNERS.keys())}"
        )

    return None


def _execute_sync(language: str, code: str) -> ExecutionResult:
    """Run *code* in a subprocess (synchronous, to be run in executor)."""
    language = language.strip().lower()

    # Validate
    validation_error = _validate_input(language, code)
    if validation_error is not None:
        return validation_error

    # Create a unique temporary directory for this execution
    tmp_dir = tempfile.mkdtemp(prefix="mcp_sandbox_", dir="/tmp")
    try:
        tmp_file_path = os.path.join(tmp_dir, f"script{SUFFIXES[language]}")
        with open(tmp_file_path, "w") as f:
            f.write(code)

        # Restrict permissions: owner-only read/write
        os.chmod(tmp_file_path, 0o600)

        env = _build_env()

        result = subprocess.run(
            RUNNERS[language] + [tmp_file_path],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=tmp_dir,
            env=env,
        )
        return ExecutionResult(
            stdout=result.stdout[:10000],
            stderr=result.stderr[:5000],
            exit_code=result.returncode,
        )
    except subprocess.TimeoutExpired:
        return ExecutionResult(error="Execution timeout after 30s")
    except FileNotFoundError:
        return ExecutionResult(error=f"Runtime '{RUNNERS[language][0]}' not found on PATH")
    except OSError as exc:
        logger.exception("Execution failed for language=%s", language)
        return ExecutionResult(error=f"Execution error: {exc}")
    finally:
        with contextlib.suppress(OSError):
            shutil.rmtree(tmp_dir, ignore_errors=True)


@mcp.tool(
    name="execute_code",
    description=("Execute Python, JavaScript or Bash code. Returns stdout, stderr and exit_code."),
)
async def execute_code(language: str, code: str) -> ExecutionResult:
    """Run *code* in a subprocess and return the result (async wrapper)."""
    async with _execution_semaphore:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _execute_sync, language, code)


# ── FastAPI application ──────────────────────────────────────────────────

app = FastAPI(title="MCP Sandbox")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Wire up SSE transport and /health endpoint
configure_app(app, mcp._mcp_server)  # noqa: SLF001 — upstream API gap

logger.info("MCP Sandbox starting on %s:%s", HOST, PORT)


# ── Entry point ──────────────────────────────────────────────────────


def main() -> None:
    """Start the MCP Sandbox server."""
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, limit_concurrency=50)


if __name__ == "__main__":
    main()
