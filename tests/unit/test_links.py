"""External evidence and copied dashboard links accept only their intended destinations."""

import pytest

from qualityintel.links import dashboard_path, github_run_url

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com.evil.example/o/r/actions/runs/1",
        "https://github.com@evil.example/o/r/actions/runs/1",
        "https://github.com:443/o/r/actions/runs/1",
        "http://github.com/o/r/actions/runs/1",
        "https://github.com/o/r/issues/1",
        "https://github.com/o/r/actions/runs/1?next=https://evil.example",
        "https://github.com/o/r/actions/runs/1/attempts/0",
        "https://github.com/o/r/actions/runs/1\n.evil.example",
    ],
)
def test_non_github_or_non_run_urls_are_not_evidence_links(url: str) -> None:
    """A prefix or a familiar path is not enough to trust a link from stored CI metadata."""
    assert github_run_url(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/o/r/actions/runs/1",
        "https://github.com/o/r/actions/runs/39403545716/attempts/2",
    ],
)
def test_real_actions_run_urls_are_kept(url: str) -> None:
    """A run link and GitHub's attempt-specific link remain usable."""
    assert github_run_url(url) == url


@pytest.mark.parametrize(
    "link",
    [None, "", "https://evil.example/", "//evil.example/", "\\\\evil.example\\", "/\\evil.example/"],
)
def test_dashboard_links_reject_external_or_ambiguous_destinations(link: str | None) -> None:
    """Copied dashboard links stay on this site's origin."""
    assert dashboard_path(link) is None


def test_dashboard_link_keeps_a_root_relative_route() -> None:
    """Hash routes and query strings work when opened from any deployment hostname."""
    assert dashboard_path("/#/test?key=x%29evil") == "/#/test?key=x%29evil"
