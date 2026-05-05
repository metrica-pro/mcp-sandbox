# MCP Sandbox

Lightweight [MCP](https://modelcontextprotocol.io/) server for executing code via a single tool — `execute_code`.

No Docker-in-Docker. No SQLite. No auth middleware. Just a FastAPI + FastMCP server that runs code in a subprocess. Isolation is expected to be handled at the K8s pod level.

## Supported Languages

| Language    | Runtime  |
|-------------|----------|
| Python      | `python3` |
| JavaScript  | `node`    |
| Bash        | `bash`    |

## Quick Start

### Local (Docker)

```bash
docker build -t mcp-sandbox .
docker run --rm -p 8181:8181 mcp-sandbox
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

## MCP Tool

### `execute_code`

```
Parameters:
  language  — "python" | "javascript" | "bash"
  code      — source code string

Returns:
  stdout    — captured stdout (up to 10 000 chars)
  stderr    — captured stderr (up to 5 000 chars)
  exit_code — process exit code

  OR

  error     — message if language is unsupported or execution times out (30s)
```

## Connect from LobeChat

1. Deploy the sandbox to K8s (e.g. `sandbox.api.metrica.pro`)
2. Open LobeChat → Agent Settings → MCP Plugin → **Add Streamable HTTP**
3. URL: `https://sandbox.api.metrica.pro/sse`
4. Ask: *«Посчитай факториал 10 на Python»*
5. LLM calls `execute_code("python", "import math; print(math.factorial(10))")`
6. Response: `3628800`

## Environment Variables

| Variable     | Default     | Description          |
|--------------|-------------|----------------------|
| `APP_HOST`   | `0.0.0.0`  | Bind address         |
| `APP_PORT`   | `8181`      | Bind port            |
| `LOG_LEVEL`  | `INFO`      | Logging level        |

## Architecture

```
Before                              After
─────────────────────────────       ─────────────────────────────
Docker SDK + DinD                   subprocess.run()
500+ MB image                       ~200 MB image
Container per execution             Instant in-process execution
SQLite + auth + UI                  Nothing extra
manager.py (500 lines)              execute_code() (~30 lines)
```

## License

MIT
