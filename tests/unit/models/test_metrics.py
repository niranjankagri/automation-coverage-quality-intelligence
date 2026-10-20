import pytest
from pydantic import ValidationError

from qualityintel.models.enums import Outcome
from qualityintel.models.metrics import Ratio, execution_pass_rate

pytestmark = pytest.mark.unit


def test_ratio_keeps_numerator_and_denominator() -> None:
    """A metric always carries the counts it was computed from."""
    ratio = Ratio(numerator=17, denominator=20)

    assert ratio.value == 0.85
    assert ratio.percent == 85.0
    assert str(ratio) == "85.0 % (17/20)"


def test_zero_denominator_is_not_applicable_never_zero_or_hundred() -> None:
    """Nothing to measure is reported as n/a, not as 0 % or 100 %."""
    ratio = Ratio(numerator=0, denominator=0)

    assert ratio.value is None
    assert ratio.percent is None
    assert str(ratio) == "n/a (0/0)"


def test_percent_is_rounded_to_one_decimal() -> None:
    """2 of 3 shows as 66.7 %, the value keeps full precision."""
    ratio = Ratio(numerator=2, denominator=3)

    assert ratio.percent == 66.7
    assert ratio.value == pytest.approx(0.6667, abs=1e-4)


@pytest.mark.parametrize(("numerator", "denominator"), [(3, 2), (-1, 2), (1, -1)])
def test_impossible_ratios_are_rejected(numerator: int, denominator: int) -> None:
    """A share larger than its whole, or negative counts, point to a calculation bug."""
    with pytest.raises(ValidationError):
        Ratio(numerator=numerator, denominator=denominator)


def test_pass_rate_leaves_skipped_tests_out() -> None:
    """8 passed, 1 failed, 1 error, 5 skipped: 8 of 10 verdicts passed."""
    outcomes = [Outcome.PASSED] * 8 + [Outcome.FAILED, Outcome.ERROR] + [Outcome.SKIPPED] * 5

    assert execution_pass_rate(outcomes) == Ratio(numerator=8, denominator=10)


def test_pass_rate_accepts_counts() -> None:
    """Counts per outcome give the same result as single outcomes."""
    counts = {Outcome.PASSED: 8, Outcome.FAILED: 1, Outcome.ERROR: 1, Outcome.SKIPPED: 5}

    assert execution_pass_rate(counts) == Ratio(numerator=8, denominator=10)


def test_pass_rate_of_only_skipped_tests_is_not_applicable() -> None:
    """A run that skipped everything has no verdict: n/a, not 0 % and not 100 %."""
    assert execution_pass_rate([Outcome.SKIPPED, Outcome.SKIPPED]).value is None
    assert execution_pass_rate([]).value is None
