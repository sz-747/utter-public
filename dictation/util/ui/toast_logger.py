"""
Toast logging setup

Sets up logging so the toast modules work standalone or inside the main program.
"""
import logging
import sys


def get_toast_logger(name: str) -> logging.Logger:
    """
    Get the logger for the toast modules

    Checks whether the client has set up logging:
    - If it has (the 'client' logger has handlers), use that logger
    - If not, create a standalone logger that prints to the console

    Args:
        name: Logger name (usually __name__)

    Returns:
        The configured logger
    """
    client_logger = logging.getLogger('client')

    if client_logger.handlers:
        # The client has set up logging: use its logger
        return client_logger
    else:
        # Running standalone: create our own logger
        logger = logging.getLogger(name)

        # Add console output if it has no handlers yet
        if not logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter(
                '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.DEBUG)
            logger.propagate = False  # Don't propagate when standalone

        return logger


def configure_toast_logging(level: int = logging.DEBUG) -> None:
    """
    Set up logging for the toast modules (when running standalone)

    Args:
        level: Log level
    """
    # Don't override the client's setup
    if logging.getLogger('client').handlers:
        return

    # Configure the root logger
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
