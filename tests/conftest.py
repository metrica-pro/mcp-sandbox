"""Shared test fixtures for MCP Sandbox."""

from __future__ import annotations

import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import pytest

# ── Load .env file (without python-dotenv dependency) ────────────────────


def _load_dotenv() -> None:
    """Load .env file into os.environ (simple parser, no dependency)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()


def _find_free_port() -> int:
    """Find a free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def sandbox_server():
    """Start the MCP Sandbox server as a subprocess for smoke/integration tests.

    Yields the base URL (http://host:port). The server is terminated
    after all session tests complete.
    """
    port = _find_free_port()
    env = os.environ.copy()
    env["APP_PORT"] = str(port)
    env["APP_HOST"] = "127.0.0.1"
    env["LOG_LEVEL"] = "ERROR"  # quieter tests
    # Don't set API_TOKEN for tests (auth off) unless explicitly testing auth
    env.pop("API_TOKEN", None)

    project_root = Path(__file__).resolve().parent.parent
    proc = subprocess.Popen(
        ["uv", "run", "python", "main.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(project_root),
    )

    base_url = f"http://127.0.0.1:{port}"

    # Wait up to 15 seconds for the server to be ready
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            resp = httpx.get(f"{base_url}/health", timeout=2)
            if resp.status_code == 200:
                break
        except (httpx.ConnectError, httpx.ConnectTimeout):
            time.sleep(0.5)
    else:
        proc.terminate()
        proc.wait()
        raise RuntimeError(f"Server did not become ready within 15s (port {port})")

    yield base_url

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


@pytest.fixture
def temp_work_dir():
    """Create a temporary directory for code execution tests."""
    with tempfile.TemporaryDirectory(prefix="mcp_test_") as d:
        yield Path(d)


@pytest.fixture
def anyio_backend():
    return "asyncio"
