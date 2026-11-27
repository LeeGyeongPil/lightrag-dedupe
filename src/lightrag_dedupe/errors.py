"""Exceptions that carry a message key (translated at the CLI boundary) and an exit code."""

from __future__ import annotations

EXIT_OK = 0
EXIT_USAGE = 2  # bad input or usage: missing graphml, malformed plan, missing extra
EXIT_STALE = 3  # the plan no longer matches the current graph
EXIT_APPLY = 4  # a merge failed while applying (409, 400, exception)


class DedupeError(Exception):
    """Base error. ``key`` indexes the message table, ``params`` fill its placeholders."""

    exit_code = EXIT_USAGE

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(key)
        self.key = key
        self.params = params


class UsageError(DedupeError):
    """Bad input or usage (exit code 2)."""

    exit_code = EXIT_USAGE


class StalePlanError(DedupeError):
    """The plan does not match the graph (exit code 3)."""

    exit_code = EXIT_STALE


class ApplyError(DedupeError):
    """A merge failed while applying (exit code 4)."""

    exit_code = EXIT_APPLY
