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


# What a parser raises when a file has an unexpected shape: a string where an object belongs,
# nesting deeper than Python's recursion limit, an encoding the XML parser cannot read.
# Importers turn these into MalformedResultError, so a hostile or broken file is an input
# problem (exit code 3), never a crash (exit code 4).
STRUCTURE_ERRORS = (AttributeError, TypeError, KeyError, IndexError, ValueError, RecursionError)


def unexpected_structure(source: str, error: BaseException) -> MalformedResultError:
    """The error to raise for a file whose structure made the parser fail."""
    if isinstance(error, RecursionError):
        return MalformedResultError(source, "nested too deeply to be a result file")
    return MalformedResultError(source, f"structure is not as expected ({type(error).__name__}: {error})")


class NoResultFilesError(IngestError):
    """A path or pattern matched no result files at all."""
