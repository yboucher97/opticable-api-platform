from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .utils import ensure_directory


def configure_logging(log_dir: Path) -> logging.Logger:
    ensure_directory(log_dir)
    logger = logging.getLogger("site_workflow")
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

    # Diagnostic logs are expendable; durable action/reconciliation evidence is
    # kept in separate journals. Bound this file even between host rotations.
    file_handler = RotatingFileHandler(
        log_dir / "site_workflow.log", maxBytes=5 * 1024 * 1024,
        backupCount=4, encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    return logger
