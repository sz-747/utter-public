# coding: utf-8

import os
import sys
import logging
import tempfile
from pathlib import Path
from logging.handlers import RotatingFileHandler
from datetime import datetime


def _running_tests() -> bool:
    """True under `python -m unittest` (or pytest)."""
    spec = getattr(sys.modules.get('__main__'), '__spec__', None)
    return bool(spec and spec.name.startswith('unittest')) or 'pytest' in sys.modules


class Logger:
    """Logging manager"""

    _loggers = {}

    @classmethod
    def setup(cls, name: str, log_dir: str = None, level: str = 'INFO', max_bytes: int = 10 * 1024 * 1024, backup_count: int = 5, log_filename: str = None):
        """
        Set up and return a logger

        Args:
            name: logger name (usually 'client')
            log_dir: log folder, the logs folder in the project root by default
            level: log level: 'DEBUG', 'INFO', 'WARNING', 'ERROR' or 'CRITICAL'
            max_bytes: maximum size of one log file, 10 MB by default
            backup_count: number of log files to keep, 5 by default
            log_filename: custom log file name prefix; defaults to name or 'root'

        Returns:
            logging.Logger: the configured logger
        """
        # Log level
        log_level = getattr(logging, level.upper(), logging.INFO)

        # Already set up: update the level and return it
        if name in cls._loggers:
            logger = cls._loggers[name]
            logger.setLevel(log_level)
            # Update the level of every handler
            for handler in logger.handlers:
                handler.setLevel(log_level)
            return logger

        # Create the logger
        # (an empty name gets the root logger)
        logger = logging.getLogger(name if name else None)
        logger.setLevel(log_level)

        # Do not propagate to the root logger (only applies to non-root loggers)
        if name:
            logger.propagate = False

        # Log folder
        if log_dir is None and _running_tests():
            # Test runs log their fake dictations elsewhere, so they never show up in the client's
            # real log (Utter's diagnosis skill reads it)
            log_dir = os.path.join(tempfile.gettempdir(), 'utter-test-logs')
        elif log_dir is None:
            from config_client import BASE_DIR
            log_dir = os.path.join(BASE_DIR, 'logs')

        # Create the log folder
        Path(log_dir).mkdir(parents=True, exist_ok=True)

        # Log file name (includes the date)
        if log_filename:
             file_name_prefix = log_filename
        elif not name:
             file_name_prefix = 'root'
        else:
             file_name_prefix = name

        log_file = os.path.join(log_dir, f'{file_name_prefix}_{datetime.now().strftime("%Y%m%d")}.log')

        # Formatter
        formatter = logging.Formatter(
            fmt='%(asctime)s.%(msecs)03d - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
            datefmt='%H:%M:%S'
        )

        # File handler (rotating)
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8'
        )
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

        # Cache the logger
        cls._loggers[name] = logger

        return logger

    @classmethod
    def get_logger(cls, name: str):
        """
        Return a logger that was already set up, or set up a default one

        Args:
            name: logger name

        Returns:
            logging.Logger: the logger
        """
        if name not in cls._loggers:
            # Not set up yet: create a default one (INFO level)
            # core_client.py sets it up again later with the right level
            return cls.setup(name, level='INFO')
        return cls._loggers[name]


# Convenience functions
def setup_logger(name: str, log_dir: str = None, level: str = 'INFO', **kwargs):
    """Convenience function that sets up a logger"""
    return Logger.setup(name, log_dir, level, **kwargs)


def get_logger(name: str):
    """Convenience function that returns a logger"""
    return Logger.get_logger(name)
