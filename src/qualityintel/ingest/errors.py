"""Errors raised while reading result files.

Each error names the file, so a pipeline log says which artefact is broken. All of them
derive from :class:`IngestError`; a quality gate treats any of them as "results incomplete",
never as success.
"""

from __future__ import annotations


class IngestError(ValueError):
    """A result file could not be imported."""

    def __init__(self, source: str, reason: str) -> None:
        super().__init__(f"{source}: {reason}")
        self.source = source
        self.reason = reason


class MalformedResultError(IngestError):
    """The file is not well-formed, or a required value is missing or invalid."""


class UnsupportedFormatError(IngestError):
    """The file is well-formed but not a format this importer reads."""


class NoResultFilesError(IngestError):
    """A path or pattern matched no result files at all."""
