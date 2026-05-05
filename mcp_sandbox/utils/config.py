"""Configuration and logging setup for MCP Sandbox."""

from __future__ import annotations

import logging
import os

# Server configuration (override via environment variables)
HOST: str = os.environ.get("APP_HOST", "0.0.0.0")
PORT: int = int(os.environ.get("APP_PORT", "8181"))
LOG_LEVEL: str = os.environ.get("LOG_LEVEL", "INFO").upper()

# Configure logging
logger = logging.getLogger("MCP_SANDBOX")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
logger.propagate = False


class ColorFormatter(logging.Formatter):
    """Color formatter for console logs (ANSI escape codes)."""

    COLOR_MAP: dict[int, str] = {
        logging.DEBUG: "\033[37m",  # white
        logging.INFO: "\033[32m",  # green
        logging.WARNING: "\033[33m",  # yellow
        logging.ERROR: "\033[31m",  # red
        logging.CRITICAL: "\033[41m",  # red background
    }
    RESET_SEQ: str = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        msg = super().format(record)
        color = self.COLOR_MAP.get(record.levelno, self.RESET_SEQ)
        return f"{color}{msg}{self.RESET_SEQ}"


console_handler = logging.StreamHandler()
console_handler.setFormatter(ColorFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logger.addHandler(console_handler)
