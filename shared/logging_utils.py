"""Consistent logging configuration for every pipeline."""
import logging
import sys


def get_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """Return a logger that writes timestamped lines to stdout.

    Calling this function several times with the same name is safe: handlers
    are only attached once.
    """
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(handler)
        logger.setLevel(level)
        logger.propagate = False
    return logger
