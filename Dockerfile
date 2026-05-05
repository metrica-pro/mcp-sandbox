FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv for package management
RUN pip install --no-cache-dir uv

# Copy dependency files
COPY pyproject.toml ./

# Install Python dependencies (uv resolves from scratch,
# uv.lock is stale from upstream Chinese mirrors)
RUN uv sync --no-dev

# Copy application code
COPY main.py config.toml ./
COPY mcp_sandbox/ ./mcp_sandbox/
COPY sandbox_images/ ./sandbox_images/

# MCP SSE endpoint
EXPOSE 8181

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8181/health || exit 1

# Run the MCP sandbox server
CMD ["uv", "run", "python", "main.py"]
