FROM python:3.12-slim

# Node.js + bash (for execute_code runtimes)
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv for package management
RUN pip install --no-cache-dir uv

# Install Python dependencies
COPY pyproject.toml .
RUN uv sync --no-dev

# Copy application code
COPY main.py ./
COPY mcp_sandbox/ ./mcp_sandbox/

# MCP SSE endpoint
EXPOSE 8181

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8181/health || exit 1

# Run the MCP sandbox server
CMD ["uv", "run", "python", "main.py"]
