import logging
import os

# Server configuration (override via environment variables)
HOST = os.environ.get("APP_HOST", "0.0.0.0")
PORT = int(os.environ.get("APP_PORT", "8181"))
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Configure logging
logger = logging.getLogger("MCP_SANDBOX")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
logger.propagate = False

formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")


class ColorFormatter(logging.Formatter):
    """Color formatter for console logs."""

    COLOR_MAP = {
        logging.DEBUG: "\033[37m",
        logging.INFO: "\033[32m",
        logging.WARNING: "\033[33m",
        logging.ERROR: "\033[31m",
        logging.CRITICAL: "\033[41m",
    }
    RESET_SEQ = "\033[0m"

    def format(self, record):
        msg = super().format(record)
        color = self.COLOR_MAP.get(record.levelno, self.RESET_SEQ)
        return f"{color}{msg}{self.RESET_SEQ}"


console_handler = logging.StreamHandler()
console_handler.setFormatter(
    ColorFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
)
logger.addHandler(console_handler)
