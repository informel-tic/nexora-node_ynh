"""Centralized logging configuration for Nexora."""

import logging
import os
import json
import sys
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def setup_logging(level=None):
    if level is None:
        level = os.environ.get("NEXORA_LOG_LEVEL", "INFO").upper()

    logger = logging.getLogger()
    logger.setLevel(level)

    # Root handler
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)

        if os.environ.get("NEXORA_JSON_LOGS") == "1":
            handler.setFormatter(JsonFormatter())
        else:
            handler.setFormatter(
                logging.Formatter(
                    "[%(asctime)s] %(levelname)s in %(name)s: %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )

        logger.addHandler(handler)

    # Silicon silence (FastAPI/Uvicorn defaults)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)

    return logger
