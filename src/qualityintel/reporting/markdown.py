"""Untrusted text in Markdown (CI job summaries): shown literally, never as links, images or HTML."""

from __future__ import annotations

import re

# Markdown punctuation that can start a link, image, emphasis, code, heading, HTML tag or table cell
_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+!<>|~])")


def md(value: object) -> str:
    """Untrusted text as literal Markdown: every special character escaped, one line.

    Test names and failure messages end up in a CI job summary; a name like
    ``[click](https://...)`` or ``<img src=...>`` must show as text, not as a link or an image.
    """
    return _SPECIAL.sub(r"\\\1", " ".join(str(value).splitlines()))


def md_code(value: object) -> str:
    """Text for inside a code span, where escapes do not work: backticks and line breaks removed."""
    return " ".join(str(value).replace("`", "'").splitlines())
