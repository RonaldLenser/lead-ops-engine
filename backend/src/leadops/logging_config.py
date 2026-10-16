"""Structured logging.

Every log line is a set of key/value pairs. In test and prod they are
rendered as one JSON object per line; locally as readable colored text.

Two sources of logs are unified here:

- our code, which logs through structlog
- libraries (uvicorn, SQLAlchemy, Alembic), which log through the standard
  library `logging` module. Their records are routed through the same
  processors, so production output is JSON from every source.

Tracebacks are rendered WITHOUT local variables. structlog can include each
frame's locals, which would copy request data, personal data, or secrets into
the logs.

Named logging_config.py (not logging.py) so it never shadows the standard
library module.
"""

import logging
import sys

import structlog
from structlog.tracebacks import ExceptionDictTransformer
from structlog.typing import Processor

# Library loggers that install their own handlers. We remove those handlers and
# let records propagate to the root handler configured below.
_LIBRARY_LOGGERS = ("uvicorn", "uvicorn.error", "alembic", "sqlalchemy")


def _renderer(json_logs: bool) -> list[Processor]:
    if json_logs:
        return [
            structlog.processors.ExceptionRenderer(ExceptionDictTransformer(show_locals=False)),
            structlog.processors.JSONRenderer(),
        ]
    return [structlog.dev.ConsoleRenderer()]


def configure_logging(level: str, json_logs: bool) -> None:
    level_number = logging.getLevelNamesMapping()[level]
    shared: list[Processor] = [
        structlog.contextvars.merge_contextvars,  # request_id and other bound context
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    # Our own logs.
    structlog.configure(
        processors=[*shared, structlog.processors.StackInfoRenderer(), *_renderer(json_logs)],
        wrapper_class=structlog.make_filtering_bound_logger(level_number),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=False,
    )

    # Library logs (standard `logging`), rendered by the same processors.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[*shared, structlog.stdlib.add_logger_name],
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                *_renderer(json_logs),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level_number)
    for name in _LIBRARY_LOGGERS:
        library_logger = logging.getLogger(name)
        library_logger.handlers = []
        library_logger.propagate = True

    # Our middleware writes the access log, with request_id. Uvicorn's own
    # access log would duplicate every request, so it is switched off here
    # regardless of how uvicorn was started.
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.handlers = []
    uvicorn_access.propagate = False

    # SQL statements and their parameters will contain personal data from M2
    # on. They are never logged unless DB_ECHO is turned on for local debugging
    # (SQLAlchemy then raises its own engine logger to INFO).
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
