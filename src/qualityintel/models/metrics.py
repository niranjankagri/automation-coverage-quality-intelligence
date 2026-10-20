"""Metric values and the execution pass rate.

Every metric is a :class:`Ratio` that keeps its numerator and denominator, so a report can
always show "17 of 20" next to "85.0 %" and a reader can check the arithmetic. Formulas and
denominators are defined in docs/metrics.md.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from qualityintel.models.enums import Outcome

NOT_APPLICABLE = "n/a"


class Ratio(BaseModel):
    """``numerator`` of ``denominator``; undefined (not 0 %) when the denominator is zero."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    numerator: Annotated[int, Field(ge=0)]
    denominator: Annotated[int, Field(ge=0)]

    @model_validator(mode="after")
    def _part_of_the_whole(self) -> Self:
        """A share can never be larger than the whole."""
        if self.numerator > self.denominator:
            raise ValueError(f"numerator {self.numerator} is larger than denominator {self.denominator}")
        return self

    @property
    def value(self) -> float | None:
        """Share between 0 and 1, or ``None`` when there is nothing to measure."""
        return None if self.denominator == 0 else self.numerator / self.denominator

    @property
    def percent(self) -> float | None:
        """Share in percent, rounded to one decimal, or ``None`` when not applicable."""
        value = self.value
        return None if value is None else round(value * 100, 1)

    def __str__(self) -> str:
        """``"85.0 % (17/20)"``, or ``"n/a (0/0)"`` when the denominator is zero."""
        shown = NOT_APPLICABLE if self.percent is None else f"{self.percent:.1f} %"
        return f"{shown} ({self.numerator}/{self.denominator})"


def execution_pass_rate(outcomes: Iterable[Outcome] | Mapping[Outcome, int]) -> Ratio:
    """Passed executions of all executions that reached a verdict.

    Skipped tests are left out of the denominator: a skip says nothing about the product, and
    counting it as "not passed" would let a run with many skips look broken (or, counted as
    passed, look healthy). Skips are reported separately.

    Args:
        outcomes: One outcome per execution, or counts per outcome.
    """
    counts = dict(outcomes) if isinstance(outcomes, Mapping) else _count(outcomes)
    passed = counts.get(Outcome.PASSED, 0)
    verdicts = passed + counts.get(Outcome.FAILED, 0) + counts.get(Outcome.ERROR, 0)
    return Ratio(numerator=passed, denominator=verdicts)


def _count(outcomes: Iterable[Outcome]) -> dict[Outcome, int]:
    """Count outcomes from an iterable."""
    counts: dict[Outcome, int] = {}
    for outcome in outcomes:
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts
