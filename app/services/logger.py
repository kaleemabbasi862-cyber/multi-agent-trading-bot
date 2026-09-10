import os
import sys
import re
import time
import logging
from logging.handlers import RotatingFileHandler
from typing import List, Dict, Any, Optional
import datetime
from collections import deque

# In-memory buffer to store recent log entries for the UI dashboard
MAX_LOG_BUFFER_SIZE = 500
_LOG_BUFFER: deque = deque(maxlen=MAX_LOG_BUFFER_SIZE)

# Patterns that might contain sensitive secrets
SECRET_PATTERNS = [
    re.compile(r'(?i)(client_secret|access_token|refresh_token|password|secret|token|api_key|authorization)[\s:=]+([a-zA-Z0-9_\-\.]{8,})'),
    re.compile(r'(?i)(Bearer\s+)([a-zA-Z0-9_\-\.]{8,})'),
]

class SecretMaskingFilter(logging.Filter):
    """
    Logging filter that automatically redacts API keys, passwords, and OAuth tokens.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = self.mask_secrets(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: (self.mask_secrets(str(v)) if isinstance(v, str) else v) for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(self.mask_secrets(str(a)) if isinstance(a, str) else a for a in record.args)
        return True

    @staticmethod
    def mask_secrets(text: str) -> str:
        for pat in SECRET_PATTERNS:
            def _replace(match):
                prefix = match.group(1)
                secret = match.group(2)
                if len(secret) > 6:
                    masked = secret[:3] + "***MASKED***" + secret[-2:]
                else:
                    masked = "***MASKED***"
                return f"{prefix}{' ' if not prefix.endswith(('=', ':')) else ''}{masked}"
            text = pat.sub(_replace, text)
        return text


class MemoryBufferLogHandler(logging.Handler):
    """
    Stores log records in an in-memory ring buffer for retrieval by the UI.
    """
    def emit(self, record: logging.LogRecord):
        try:
            entry = {
                "timestamp": datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "module": record.name,
                "message": record.getMessage(),
                "correlation_id": getattr(record, "correlation_id", "-")
            }
            _LOG_BUFFER.append(entry)
        except Exception:
            self.handleError(record)


def setup_structured_logging(log_dir: str = "logs", log_level: int = logging.INFO):
    """
    Initializes structured rotating file logging, console logging with UTF-8, and UI memory buffer.
    """
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "tradetalk.log")

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Secret masking filter
    masking_filter = SecretMaskingFilter()

    # Formatter
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 1. Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    console_handler.addFilter(masking_filter)

    # 2. Rotating File Handler (5 MB per file, max 5 backups)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(masking_filter)

    # 3. Memory Buffer Handler
    buffer_handler = MemoryBufferLogHandler()
    buffer_handler.setLevel(log_level)
    buffer_handler.addFilter(masking_filter)

    # Clear existing handlers
    root_logger.handlers.clear()
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(buffer_handler)


def get_recent_logs(limit: int = 100, level_filter: Optional[str] = None) -> List[Dict[str, Any]]:
    """Retrieves recent logs from the in-memory buffer."""
    logs = list(_LOG_BUFFER)
    if level_filter and level_filter.upper() != "ALL":
        target = level_filter.upper()
        logs = [l for l in logs if l["level"] == target]
    return logs[-limit:]
