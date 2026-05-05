"""MCP Sandbox — lightweight code execution server.

Provides a single MCP tool ``execute_code`` that runs Python, JavaScript
or Bash code inside the current process (no Docker). Isolation is
expected to be enforced at the K8s pod level (securityContext, limits).

Streamable HTTP 2025 (POST /sse) — compatible with LobeChat, Claude, Cursor.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import TypedDict

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastmcp import FastMCP

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

# Execution timeout — SIGTERM sent after this many seconds
EXECUTION_TIMEOUT: int = 30

# Grace period after SIGTERM before sending SIGKILL
KILL_GRACE_PERIOD: int = 2

# Hard deadline — if process still alive after this, background cron kills it
HARD_TIMEOUT: int = EXECUTION_TIMEOUT + KILL_GRACE_PERIOD + 5

# Background killer interval (seconds)
CRON_INTERVAL: int = 15

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
    # External API keys (read from .env / K8s secrets)
    "YANDEX_API_KEY",
    "YANDEX_FOLDER_ID",
    "MINIMAX_API_KEY",
}

# ── Authentication ───────────────────────────────────────────────────────

API_TOKEN: str | None = os.environ.get("API_TOKEN")

_auth_required: bool = bool(API_TOKEN)

if _auth_required:
    logger.info("API_TOKEN configured — Bearer token authentication enabled")
else:
    logger.warning(
        "API_TOKEN not set — endpoint is OPEN (no authentication). "
        "Set API_TOKEN env var to enable Bearer token auth."
    )


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

# ── Process tracking for hung-process killer ─────────────────────────────

# Tracks running subprocesses: {pid: (start_time, pgid)}
_running_procs: dict[int, tuple[float, int]] = {}
_running_procs_lock = threading.Lock()


def _track_process(pid: int, pgid: int) -> None:
    """Register a running subprocess for the background killer."""
    with _running_procs_lock:
        _running_procs[pid] = (time.monotonic(), pgid)


def _untrack_process(pid: int) -> None:
    """Remove a process from tracking (called on normal completion)."""
    with _running_procs_lock:
        _running_procs.pop(pid, None)


async def _hung_process_killer() -> None:
    """Background task that periodically kills hung processes.

    Checks immediately on first tick, then every ``CRON_INTERVAL`` seconds.
    Any tracked process that has been running longer than ``HARD_TIMEOUT``
    gets a SIGKILL delivered to its entire process group.
    """
    first_tick = True
    while True:
        if first_tick:
            first_tick = False
        else:
            await asyncio.sleep(CRON_INTERVAL)
        now = time.monotonic()
        with _running_procs_lock:
            stale_pids: list[tuple[int, int]] = []
            for pid, (start, pgid) in list(_running_procs.items()):
                if now - start >= HARD_TIMEOUT:
                    stale_pids.append((pid, pgid))
            for pid, pgid in stale_pids:
                logger.warning(
                    "Cron killer: pid=%s pgid=%s hung for >%ss — sending SIGKILL",
                    pid,
                    pgid,
                    HARD_TIMEOUT,
                )
                with contextlib.suppress(ProcessLookupError, PermissionError, OSError):
                    os.killpg(pgid, signal.SIGKILL)
                _running_procs.pop(pid, None)


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

        # Use Popen for fine-grained timeout control:
        #   1. SIGTERM to process group after EXECUTION_TIMEOUT
        #   2. SIGKILL after KILL_GRACE_PERIOD (non-ignorable)
        #   3. start_new_session=True → new pgid, children killed too
        proc = subprocess.Popen(
            RUNNERS[language] + [tmp_file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=tmp_dir,
            env=env,
            start_new_session=True,
        )

        # Register for background cron killer
        _track_process(proc.pid, proc.pid)

        try:
            stdout_str, stderr_str = proc.communicate(timeout=EXECUTION_TIMEOUT)
        except subprocess.TimeoutExpired:
            # Phase 1: SIGTERM to the entire process group
            logger.warning(
                "Timeout %ss — SIGTERM pgid=%s",
                EXECUTION_TIMEOUT,
                proc.pid,
            )
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGTERM)

            try:
                stdout_str, stderr_str = proc.communicate(timeout=KILL_GRACE_PERIOD)
            except subprocess.TimeoutExpired:
                # Phase 2: SIGKILL — guaranteed kill
                logger.warning(
                    "Process pgid=%s survived SIGTERM — SIGKILL",
                    proc.pid,
                )
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(proc.pid, signal.SIGKILL)
                stdout_str, stderr_str = proc.communicate()

            _untrack_process(proc.pid)
            return ExecutionResult(error="Execution timeout after 30s")
        except FileNotFoundError:
            _untrack_process(proc.pid)
            return ExecutionResult(error=f"Runtime '{RUNNERS[language][0]}' not found on PATH")
        except OSError as exc:
            _untrack_process(proc.pid)
            logger.exception("Execution failed for language=%s", language)
            return ExecutionResult(error=f"Execution error: {exc}")
        else:
            _untrack_process(proc.pid)
            return ExecutionResult(
                stdout=(stdout_str or "")[:10000],
                stderr=(stderr_str or "")[:5000],
                exit_code=proc.returncode,
            )
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


# ── Build ASGI app (MCP http_app as base, extended with auth/health) ─────

# Get the MCP Streamable HTTP app (Starlette)
mcp_app = mcp.http_app(transport="streamable-http", path="/sse")

# Merge lifespans: our cron killer + MCP session manager
_original_mcp_lifespan = mcp_app.router.lifespan_context


@contextlib.asynccontextmanager
async def merged_lifespan(application: FastAPI) -> AsyncIterator[None]:
    """Start cron killer, then MCP session manager."""
    # Start cron killer
    killer_task = asyncio.create_task(_hung_process_killer())
    logger.info(
        "Background cron killer started (interval=%ss, hard_timeout=%ss)",
        CRON_INTERVAL,
        HARD_TIMEOUT,
    )
    # Start MCP session manager
    async with _original_mcp_lifespan(mcp_app):
        yield
    # Shutdown cron killer
    killer_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await killer_task
    logger.info("Background cron killer stopped")


# Create FastAPI app with merged lifespan
app = FastAPI(title="MCP Sandbox", lifespan=merged_lifespan)

# ── Auth middleware ───────────────────────────────────────────────────────


@app.middleware("http")
async def auth_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Validate Bearer token if API_TOKEN is configured.

    /health is exempt from authentication.
    """
    if request.url.path == "/health":
        return await call_next(request)

    if _auth_required:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={
                    "error": "Missing or malformed Authorization header. "
                    "Use: Authorization: Bearer <token>"
                },
            )
        token = auth_header.removeprefix("Bearer ")
        if API_TOKEN and token != API_TOKEN:
            return JSONResponse(
                status_code=403,
                content={"error": "Invalid API token"},
            )

    return await call_next(request)


# CORS (required for browser-based MCP clients like LobeChat)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check (no auth required)
@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


# ── Mount MCP app ────────────────────────────────────────────────────────

# Mount the MCP Streamable HTTP app at root.
# The merged lifespan ensures the MCP session manager is initialized.
app.mount("/", mcp_app)


logger.info(
    "MCP Sandbox starting on %s:%s (auth=%s, transport=streamable-http)",
    HOST,
    PORT,
    "on" if _auth_required else "off",
)


# ── Entry point ──────────────────────────────────────────────────────────


def main() -> None:
    """Start the MCP Sandbox server."""
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT, limit_concurrency=50)


if __name__ == "__main__":
    main()
