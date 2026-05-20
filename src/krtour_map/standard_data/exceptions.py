from __future__ import annotations


class StandardDataError(Exception):
    """Base error for the bounded data.go.kr standard-data client."""


class StandardDataConfigError(StandardDataError):
    """Raised when required client configuration is missing."""


class StandardDataHttpError(StandardDataError):
    """Raised when a standard-data HTTP response cannot be used."""


class StandardDataParseError(StandardDataError):
    """Raised when a standard-data payload does not match the expected shape."""
