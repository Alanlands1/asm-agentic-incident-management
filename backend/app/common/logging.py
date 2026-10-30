"""Logging configuration."""

import logging
import sys

from app.common.config import settings


def setup_logging() -> None:
    """Configures application-wide logging."""
    log_format = "%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s"
    logging.basicConfig(
        level=settings.LOG_LEVEL.upper(),
        format=log_format,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=True,
    )
