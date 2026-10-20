from importlib.metadata import version

import pytest

import qualityintel

pytestmark = pytest.mark.unit


def test_version_matches_the_installed_distribution() -> None:
    """`__version__` and pyproject.toml must not drift apart (both are edited by hand)."""
    assert qualityintel.__version__ == version("automation-coverage-quality-intelligence")
