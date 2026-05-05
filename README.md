# MCP Sandbox

Lightweight [MCP](https://modelcontextprotocol.io/) server for executing code via a single tool — `execute_code`.

No Docker-in-Docker. No SQLite. No auth middleware. Just a FastAPI + FastMCP server that runs code in a subprocess. Isolation is expected to be handled at the K8s pod level.

## Supported Languages

| Language    | Runtime    |
|-------------|------------|
| Python      | `python3`  |
| JavaScript  | `node`     |
| Bash        | `bash`     |

## Quick Start

### Local (Docker)

```bash
docker build -t mcp-sandbox .
docker run --rm -p 8181:8181 mcp-sandbox
```

### Local (uv)

```bash
uv sync
uv run python main.py
```

### Health check

```bash
curl http://localhost:8181/health
# {"status":"ok"}
```

### SSE endpoint

```bash
curl -v http://localhost:8181/sse
# Long-lived SSE connection
```

## MCP Tool: `execute_code`

```
Parameters:
  language  — "python" | "javascript" | "bash"  (case-insensitive)
  code      — source code string (max 1 MB)

Returns:
  stdout    — captured stdout (up to 10 000 chars)
  stderr    — captured stderr (up to 5 000 chars)
  exit_code — process exit code
  error     — message if language unsupported, code empty, or timeout (30s)
```

### Example via curl

```bash
# List tools
curl -s http://localhost:8181/sse  # (MCP SSE protocol)

# Or use the MCP Python client:
python test_mcp.py
```

## Security & Isolation

| Feature | Detail |
|---|---|
| **Per-request temp dir** | Unique `mktemp` per execution, `chmod 0o600` |
| **Process group** | `start_new_session=True` — kill children with parent |
| **Two-phase timeout** | SIGTERM at 30s → 2s grace → SIGKILL (non-ignorable) |
| **Cron killer** | Background asyncio task kills processes hung >37s |
| **Rate limiting** | `asyncio.Semaphore(10)` max concurrent executions |
| **Env whitelist** | Only `PATH`, `HOME`, `LANG`, `PYTHONUNBUFFERED`, and explicit API keys pass through |
| **Size limit** | Code capped at 1 MB |
| **Output truncation** | stdout ≤ 10k chars, stderr ≤ 5k chars |
| **K8s isolation** | Pod-level `securityContext` for defense-in-depth |

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `APP_HOST` | `0.0.0.0` | Bind address |
| `APP_PORT` | `8181` | Bind port |
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `YANDEX_API_KEY` | — | Yandex Search API key (optional) |
| `YANDEX_FOLDER_ID` | — | Yandex Cloud folder ID (optional) |
| `MINIMAX_API_KEY` | — | MiniMax Platform API key (optional) |

Place API keys in `.env` file (gitignored) or K8s secrets.

## Real API Integration (via execute_code)

The sandbox can call external APIs. The Python script runs in the sandboxed subprocess, makes HTTPS calls, parses the response, and returns structured JSON.

### MiniMax Chat (AI)

```python
# Script sent to execute_code:
"""
import os, json, urllib.request

API_KEY = os.environ["MINIMAX_API_KEY"]
req = urllib.request.Request(
    "https://api.minimax.io/v1/chat/completions",
    data=json.dumps({
        "model": "MiniMax-M2.7",
        "messages": [{"role": "user", "content": "What is 2+2?"}]
    }).encode(),
    headers={"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    result = json.loads(resp.read().decode())
    reply = result["choices"][0]["message"]["content"]
    print(json.dumps({"reply": reply, "usage": result["usage"]}))
"""
```

### Yandex Search API

```python
# Script sent to execute_code:
"""
import os, json, base64, urllib.request, xml.etree.ElementTree as ET

API_KEY = os.environ["YANDEX_API_KEY"]
FOLDER_ID = os.environ["YANDEX_FOLDER_ID"]
# ... POST to /v2/web/search, decode base64 XML, parse with ElementTree ...
print(json.dumps({"items": [{"title": "...", "url": "..."}]}))
"""
```

## Connect from LobeChat

1. Deploy the sandbox to K8s (e.g. `sandbox.api.metrica.pro`)
2. Open LobeChat → Agent Settings → MCP Plugin → **Add Streamable HTTP**
3. URL: `https://sandbox.api.metrica.pro/sse`
4. Ask: *«Посчитай факториал 10 на Python»*
5. LLM calls `execute_code("python", "import math; print(math.factorial(10))")`
6. Response: `3628800`

## Development

### Install

```bash
uv sync --all-extras
```

### Lint & Type Check

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy mcp_sandbox/ main.py --ignore-missing-imports
```

### Tests

```bash
# Unit tests (no server needed, ~30s)
uv run pytest tests/test_execute_code.py -v

# Smoke tests (starts live server)
uv run pytest tests/test_smoke.py -v

# External API tests (needs .env with API keys)
uv run pytest tests/test_minimax.py tests/test_yandex_search.py -v

# All tests
uv run pytest tests/ -v
```

### Test Suite (58 tests)

| Module | Count | What |
|---|---|---|
| `test_execute_code.py` | 35 | Validation, execution, env, timeout, process tracking, cron killer, SIGTERM→SIGKILL |
| `test_smoke.py` | 10 | Health endpoint, SSE, full MCP protocol (list_tools + execute Python/JS/Bash) |
| `test_minimax.py` | 7 | Chat completion via MCP, reasoning mode, edge cases |
| `test_yandex_search.py` | 6 | Search API via MCP, XML parsing, edge cases |

## CI/CD

GitHub Actions workflow (`.github/workflows/build.yml`):

```
push/PR → test job (ruff → mypy → unit tests → smoke test)
              ↓
         build job (Docker build & push to GHCR)
```

Image: `ghcr.io/metrica-pro/mcp-sandbox:latest`

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

## License

MIT
