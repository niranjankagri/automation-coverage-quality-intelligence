import pytest
from pydantic import ValidationError

from qualityintel.models.enums import Outcome
from qualityintel.models.results import MAX_FAILURE_TEXT, FailureDetails, TestResult, TestRun

pytestmark = pytest.mark.unit

RUN_ID = "a" * 64


def test_key_combines_classname_and_name() -> None:
    """The key identifies a test across runs; without a classname the name alone is used."""
    with_class = TestResult(name="test_login", classname="tests.api.test_auth", outcome=Outcome.PASSED)
    without_class = TestResult(name="Login Works", outcome=Outcome.PASSED)

    assert with_class.key == "tests.api.test_auth::test_login"
    assert without_class.key == "Login Works"


@pytest.mark.parametrize(
    ("outcome", "retries", "expected"),
    [
        (Outcome.PASSED, 1, True),
        (Outcome.PASSED, 0, False),
        (Outcome.FAILED, 2, False),
    ],
)
def test_passed_after_retry_needs_both_a_pass_and_a_retry(
    outcome: Outcome, retries: int, expected: bool
) -> None:
    """Only a pass that needed extra attempts is a flaky signal inside one run."""
    result = TestResult(name="t", outcome=outcome, retries=retries)

    assert result.passed_after_retry is expected


@pytest.mark.parametrize(
    "fields",
    [
        {"name": "", "outcome": "passed"},
        {"name": "t", "outcome": "broken"},
        {"name": "t", "outcome": "passed", "duration_seconds": -0.1},
        {"name": "t", "outcome": "passed", "retries": -1},
    ],
    ids=["empty-name", "unknown-outcome", "negative-duration", "negative-retries"],
)
def test_invalid_results_are_rejected(fields: dict[str, object]) -> None:
    """Values that cannot come from a real execution are errors."""
    with pytest.raises(ValidationError):
        TestResult.model_validate(fields)


def test_failure_text_has_an_upper_limit() -> None:
    """Long stack traces must be cut by the importer before they reach the model."""
    FailureDetails(text="x" * MAX_FAILURE_TEXT)

    with pytest.raises(ValidationError):
        FailureDetails(text="x" * (MAX_FAILURE_TEXT + 1))


def test_outcome_counts_include_every_outcome() -> None:
    """Counts have all four outcomes, so reports never miss a zero column."""
    run = TestRun(
        run_id=RUN_ID,
        source="junit.xml",
        results=(
            TestResult(name="a", outcome=Outcome.PASSED),
            TestResult(name="b", outcome=Outcome.PASSED),
            TestResult(name="c", outcome=Outcome.FAILED),
        ),
    )

    assert run.outcome_counts() == {
        Outcome.PASSED: 2,
        Outcome.FAILED: 1,
        Outcome.ERROR: 0,
        Outcome.SKIPPED: 0,
    }


def test_run_id_must_be_a_sha256_hex_digest() -> None:
    """Run ids are content hashes; anything else points to a bug in the importer."""
    with pytest.raises(ValidationError):
        TestRun(run_id="run-1", source="junit.xml", results=())
