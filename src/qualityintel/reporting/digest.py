"""The daily quality digest as plain text and Markdown (docs/digest.md).

Rendered only from :class:`DigestView`, so the digest says exactly what the dashboard's analyses
say. Each line that has evidence carries the dashboard link to it: ``#/route?params`` relative to
the dashboard, or absolute when a base URL is given (``qi digest --base-url``). Imported text
(test names, failure messages) is escaped in Markdown, so a test named ``[x](https://...)``
stays text.
"""

from __future__ import annotations

from urllib.parse import quote, urlencode

from qualityintel.reporting.investigation import Summary
from qualityintel.reporting.markdown import md
from qualityintel.workspace import DigestLine, DigestView


def dashboard_link(line: DigestLine, base_url: str = "") -> str | None:
    """The dashboard address of a line's evidence, ``None`` when the line has none."""
    if line.route is None:
        return None
    path = "/".join(quote(part, safe="") for part in line.route.strip("/").split("/"))
    query = f"?{urlencode(line.params)}" if line.params else ""
    return f"{base_url.rstrip('/')}/classic/#/{path}{query}"


def render_digest(digest: DigestView, base_url: str = "") -> Summary:
    """The digest in both formats; sections in the view's order, notes at the end."""
    title = f"Quality digest {digest.day}" if digest.day else "Quality digest"
    since = f" (compared with {digest.previous_day})" if digest.previous_day else ""
    text = [title + since, ""]
    markdown = [f"### {md(title + since)}", ""]
    for section in digest.sections:
        text.append(f"{section.title}:")
        markdown += [f"**{md(section.title)}**", ""]
        for line in section.lines:
            href = dashboard_link(line, base_url)
            text.append(f"- {line.text}" + (f" [{href}]" if href else ""))
            markdown.append(f"- [{md(line.text)}]({href})" if href else f"- {md(line.text)}")
        text.append("")
        markdown.append("")
    text += ["Notes:", *(f"- {note}" for note in digest.notes)]
    markdown += ["**Notes**", "", *(f"- {md(note)}" for note in digest.notes)]
    return Summary(text="\n".join(text) + "\n", markdown="\n".join(markdown) + "\n")
