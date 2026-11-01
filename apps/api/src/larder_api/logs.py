"""Share and calendar addresses carry their permission in the path, so they stay out of the logs:
whoever can read the access log shouldn't be able to open people's links."""

import logging
import re

__all__ = ["HideTokens"]

_TOKEN_PATH = re.compile(r"(/share/|/calendar/)[^/?\s]+")


class HideTokens(logging.Filter):
    """For uvicorn's access log, whose arguments are (client, method, path, version, status)."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            hidden = _TOKEN_PATH.sub(r"\1***", args[2])
            record.args = (*args[:2], hidden, *args[3:])
        return True
