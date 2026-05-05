# CLAUDE.md

This file provides guidance to Claude Code (claude.ai) when working with this repository.

## Project Overview

**MCP Sandbox** — a lightweight [MCP](https://modelcontextprotocol.io/) (Model Context Protocol) server for executing code via a single tool: `execute_code`. It runs Python, JavaScript, and Bash in subprocesses (no Docker-in-Docker). Isolation is enforced at the K8s pod level.

- **Version:** 0.2.1
- **Language:** Python 3.12+
- **License:** MIT
- **Container image:** `ghcr.io/metrica-pro/mcp-sandbox:latest`

## Architecture

```
┌─────────────┐     SSE      ┌──────────────┐     subprocess      ┌──────────┐
│  MCP Client  │ ←─────────→ │  FastAPI app  │ ←───────────────→ │  python3  │
│ (LobeChat,   │  /sse       │  + FastMCP    │   start_new_       │  node     │
│  Claude,     │  /messages  │               │   session=True     │  bash     │
│  Cursor...)  │             │               │                    │           │
└─────────────┘             ┌────────────────┐                  └──────────┘
                            │  Cron killer    │
                            │  (every 15s)    │
                            │  SIGKILL hung   │
                            │  processes      │
                            └────────────────┘
```

### Key Design Decisions

1. **No Docker-in-Docker** — subprocess isolation via `start_new_session=True` + K8s pod security
2. **Streamable HTTP (MCP 2025 spec)** — POST `/sse` for JSON-RPC, GET `/sse` for SSE stream
3. **Two-phase timeout** — SIGTERM (30s) → 2s grace → SIGKILL (non-ignorable)
4. **Cron killer** — Background asyncio task (every 15s) kills processes hung >37s
5. **Optional Bearer token auth** via `API_TOKEN` env var (health endpoint exempt)
6. **FastMCP 2.x** — built-in Streamable HTTP transport, NOT raw SSE via `mcp.server.sse.SseServerTransport`

## Directory Structure

```
mcp-sandbox/
├── main.py                    # Main server: FastAPI + FastMCP + tool + lifespan
├── mcp_sandbox/
│   ├── __init__.py
│   ├── main.py                # Package entry point (console_script)
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes.py          # LEGACY: old SSE routes (NOT used anymore)
│   └── utils/
│       ├── __init__.py
│       └── config.py          # HOST, PORT, LOG_LEVEL, ColorFormatter, logger
├── tests/
│   ├── __init__.py
│   ├── conftest.py            # Fixtures: sandbox_server, temp_work_dir
│   ├── test_execute_code.py   # 35 unit tests (validation, execution, timeout, tracking)
│   ├── test_smoke.py          # 10 MCP protocol tests (health, SSE, execute Python/JS/Bash)
│   ├── test_minimax.py        # 7 tests for MiniMax API via execute_code
│   └── test_yandex_search.py  # 6 tests for Yandex Search API via execute_code
├── Dockerfile                 # python:3.12-slim + nodejs
├── pyproject.toml             # uv project config, ruff, mypy, pytest settings
├── uv.lock
├── test_mcp.py                # Standalone MCP client test script
├── README.md
└── .github/
    ├── workflows/build.yml     # CI: ruff → mypy → unit tests → smoke test → Docker build
    └── dependabot.yml          # Daily uv dependency updates
```

**Important:** `mcp_sandbox/api/routes.py` contains the OLD raw SSE transport implementation (`SseServerTransport` from `mcp.server.sse`). The current server uses FastMCP's built-in `mcp.http_app(transport="streamable-http", path="/sse")` instead. The `routes.py` module is kept for reference but is NOT imported by `main.py`.

## Key Components

### `main.py` (root) — Server Core

- **Lifespan:** Starts the background cron killer (`_hung_process_killer`) on startup, cancels it on shutdown
- **Auth middleware:** Validates `Authorization: Bearer <token>` on all paths except `/health`
- **CORS:** Allows all origins (required for browser-based MCP clients)
- **MCP tool `execute_code(language, code)`:** Async wrapper around `_execute_sync`, with `Semaphore(10)` rate limiting
- **`_execute_sync(language, code)`:** Synchronous execution in a thread pool:
  1. Validates inputs via `_validate_input`
  2. Creates temp dir (`mktemp` with `0o600` permissions)
  3. Writes code to temp file with language-appropriate extension (`.py`, `.js`, `.sh`)
  4. Spawns subprocess with `start_new_session=True`
  5. Registers in `_running_procs` for cron killer tracking
  6. Two-phase timeout: `communicate(30s)` → SIGTERM → `communicate(2s)` → SIGKILL
  7. Cleans temp dir via `shutil.rmtree`
  8. Truncates stdout to 10k chars, stderr to 5k chars

### `mcp_sandbox/utils/config.py` — Configuration

- Reads `APP_HOST` (default `0.0.0.0`), `APP_PORT` (default `8181`), `LOG_LEVEL` (default `INFO`)
- `ColorFormatter`: ANSI-colored log output (green=INFO, yellow=WARNING, red=ERROR)

### `mcp_sandbox/main.py` — Package Entry Point

- Console script `mcp-sandbox` → calls `uvicorn.run(app, host=HOST, port=PORT, limit_concurrency=50)`

## MCP Tool: `execute_code`

```
Input:
  language  — "python" | "javascript" | "bash" (case-insensitive, whitespace-trimmed)
  code      — source code string (max 1 MB, must be non-empty after strip)

Output (ExecutionResult):
  stdout    — captured stdout (first 10,000 chars)
  stderr    — captured stderr (first 5,000 chars)
  exit_code — process exit code (integer)
  error     — error message if validation fails or timeout occurs (30s)
```

## Development Commands

```bash
# Install dependencies
uv sync --all-extras

# Run server locally
uv run python main.py

# Lint & format check
uv run ruff check .
uv run ruff format --check .

# Type check
uv run mypy mcp_sandbox/ main.py --ignore-missing-imports

# Unit tests (no server needed, ~30s)
uv run pytest tests/test_execute_code.py -v

# Smoke tests (starts live server via conftest fixture)
uv run pytest tests/test_smoke.py -v

# External API tests (requires .env with API keys)
uv run pytest tests/test_minimax.py tests/test_yandex_search.py -v

# All tests
uv run pytest tests/ -v

# Docker build & run
docker build -t mcp-sandbox .
docker run --rm -p 8181:8181 mcp-sandbox

# Health check
curl http://localhost:8181/health
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `APP_HOST` | `0.0.0.0` | Bind address |
| `APP_PORT` | `8181` | Bind port |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `API_TOKEN` | — | If set, enables Bearer token authentication |
| `YANDEX_API_KEY` | — | Yandex Search API key (passed to subprocess) |
| `YANDEX_FOLDER_ID` | — | Yandex Cloud folder ID |
| `MINIMAX_API_KEY` | — | MiniMax Platform API key |

Place API keys in `.env` (gitignored) or K8s secrets.

## Security Model

| Feature | Detail |
|---|---|
| Per-request temp dir | Unique `mktemp` per execution, `chmod 0o600` |
| Process group isolation | `start_new_session=True` — killpg kills children with parent |
| Two-phase timeout | SIGTERM at 30s → 2s grace → SIGKILL |
| Cron killer | Background asyncio task kills processes hung >37s |
| Rate limiting | `asyncio.Semaphore(10)` max concurrent executions |
| Env whitelist | Only `SAFE_ENV_VARS` pass through to subprocess |
| Code size limit | 1 MB hard cap |
| Output truncation | stdout ≤ 10k chars, stderr ≤ 5k chars |
| K8s isolation | Pod-level `securityContext` for defense-in-depth |

## Code Style & Conventions

- **Line length:** 100 chars (`[tool.ruff]`)
- **Python version:** 3.12
- **Quotes:** Double quotes (`[tool.ruff.format] quote-style = "double"`)
- **Lint rules:** E, F, I, N, W, UP, B, C4, SIM (with B008, S101 ignored)
- **Type checking:** `mypy` with `strict = true`, `ignore_missing_imports = true`
- **Async:** `pytest-asyncio` with `asyncio_mode = "auto"`, `loop_scope = "function"`
- **Imports:** Use `from __future__ import annotations` throughout
- **TypedDict:** `ExecutionResult` with `total=False` for optional fields

## CI/CD (GitHub Actions)

**Trigger:** push/PR to `main`, version tags `v*`, manual dispatch

1. **test job:**
   - Install uv + Python 3.12 + dependencies
   - `ruff check .` + `ruff format --check .`
   - `mypy mcp_sandbox/ main.py --ignore-missing-imports`
   - `pytest tests/ -v` (unit tests)
   - Manual smoke test: start server, check `/health`, terminate
2. **build job** (needs test job):
   - Docker build & push to `ghcr.io/metrica-pro/mcp-sandbox` (tags: `latest` + `${{ github.sha }}`)

## Test Suite (58 tests)

| Module | Count | What |
|---|---|---|
| `test_execute_code.py` | 35 | Input validation, execution (Python/JS/Bash), env building, timeout, process tracking, cron killer, SIGTERM→SIGKILL escalation |
| `test_smoke.py` | 10 | Health endpoint, SSE, full MCP protocol (list_tools + execute Python/JS/Bash) |
| `test_minimax.py` | 7 | Chat completion via MCP, reasoning mode, edge cases (invalid key/model) |
| `test_yandex_search.py` | 6 | Search API via MCP, XML parsing, edge cases (invalid key/folder/query) |

### Test Fixtures (conftest.py)

- `sandbox_server` (session-scoped): Starts a live server on a random port, yields `http://127.0.0.1:{port}`, terminates after all tests
- `temp_work_dir` (function-scoped): Temporary directory for execution tests
- `.env` loaded manually (no `python-dotenv` dependency)

## Notes for AI Agents

1. **The `routes.py` in `mcp_sandbox/api/` is LEGACY.** Do not modify it or try to use it. The actual server in `main.py` uses FastMCP's `mcp.http_app(transport="streamable-http", path="/sse")`.
2. **Imports in `main.py`** include `from mcp_sandbox.utils.config import HOST, PORT, logger` — this is the only cross-module import into `main.py`.
3. **The `mcp_sandbox/main.py`** entry point has a deferred import of `from main import app` to avoid circular imports.
4. **Tests that need API keys** skip automatically if env vars are not set (`pytest.skip(...)`).
5. **Process tracking is global** — `_running_procs` dict shared across the module, protected by `_running_procs_lock` (threading.Lock).
6. **Error handling in `_execute_sync`** catches `FileNotFoundError` (runtime not found), `OSError` (execution error), and `TimeoutExpired` (timeout).
