import logging
import sys

from config import Config


def setup_logging() -> None:
    """Call once at app startup in main.py."""
    logging.basicConfig(
        level=getattr(logging, Config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )

def get_logger(name: str) -> logging.Logger:
    """Use in every module: logger = get_logger(__name__)"""
    return logging.getLogger(name)
