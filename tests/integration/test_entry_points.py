import subprocess
import sys

import pytest

from qualityintel import __version__

pytestmark = pytest.mark.integration


def test_module_runs_as_a_separate_process() -> None:
    """`python -m qualityintel version` works the way CI pipelines will call it."""
    result = subprocess.run(
        [sys.executable, "-m", "qualityintel", "version"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"qi {__version__}"


def test_exit_code_reaches_the_calling_process() -> None:
    """A usage error is visible to the caller as exit code 2, not swallowed."""
    result = subprocess.run(
        [sys.executable, "-m", "qualityintel"],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 2
    assert "usage: qi" in result.stderr
