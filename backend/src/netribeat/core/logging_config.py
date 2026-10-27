"""Key=value logging with a redaction filter.

Logs carry ids, never personal data or secrets. The filter is a safety net: any
`extra` key that looks secret is replaced before formatting.
"""

from __future__ import annotations

import logging
import re
import sys
from typing import Any

SENSITIVE_KEY = re.compile(r"(pass|secret|token|otp|code|authorization|cookie|email)", re.I)
REDACTED = "[redacted]"
_STD_ATTRS = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{self.formatTime(record)} {record.levelname} {record.name} {record.getMessage()}"
        extras = {k: v for k, v in record.__dict__.items() if k not in _STD_ATTRS}
        if extras:
            base += " " + " ".join(f"{k}={_render(v)}" for k, v in sorted(extras.items()))
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def _render(v: Any) -> str:
    s = str(v)
    return f'"{s}"' if " " in s else s


class RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key in list(record.__dict__):
            if key not in _STD_ATTRS and SENSITIVE_KEY.search(key):
                record.__dict__[key] = REDACTED
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(KeyValueFormatter())
    handler.addFilter(RedactFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Access logs: uvicorn logs the path including the query string; we replace it
    # with our own middleware log line that omits the query string (CLAUDE.md).
    logging.getLogger("uvicorn.access").disabled = True
    # PDF rendering libraries log every font subset at INFO.
    for noisy in ("fontTools", "matplotlib"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
