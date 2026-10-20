"""Quality gate configuration (TOML).

Every threshold is optional: a rule that is not configured is not evaluated, so nothing is
hard-coded. Percentages are written as percent (``95`` = 95 %). Example
(samples/gates/release.toml)::

    [coverage]
    min_requirement_coverage = 90
    max_uncovered_critical = 0

    [execution]
    min_pass_rate = 98
    max_failing_critical = 0
    min_results = 200

    [scope]
    criticality = ["critical", "high"]

    [pipeline]
    jobs = ["api", "ui-chrome"]   # every one must report, or the gate is incomplete

Unknown keys are errors: a misspelt threshold must not silently switch a rule off.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

Percent = Annotated[float, Field(ge=0, le=100)]
Count = Annotated[int, Field(ge=0)]


class GateConfigError(ValueError):
    """The gate configuration cannot be read or contains an invalid value."""


class _Section(BaseModel):
    """Strict, immutable configuration section."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class CoverageRules(_Section):
    """Thresholds on the catalog metrics (docs/metrics.md sections 1-3)."""

    min_requirement_coverage: Percent | None = None
    min_automation_coverage: Percent | None = None
    min_automated_requirement_coverage: Percent | None = None
    max_uncovered_critical: Count | None = None
    max_requirements_without_tests: Count | None = None


class ExecutionRules(_Section):
    """Thresholds on the counted runs: latest run per context, or every run of a pipeline execution."""

    min_pass_rate: Percent | None = None
    max_failing_critical: Count | None = None
    max_failing_requirements: Count | None = None
    max_failed_tests: Count | None = None
    min_results: Count | None = None
    max_automated_cases_without_results: Count | None = None


class Scope(_Section):
    """Restrict the gate to part of the catalog or the runs (same filters as ``qi coverage``)."""

    feature: tuple[str, ...] = ()
    criticality: tuple[str, ...] = ()
    platform: tuple[str, ...] = ()
    test_type: tuple[str, ...] = ()
    framework: tuple[str, ...] = ()
    environment: tuple[str, ...] = ()
    browser: tuple[str, ...] = ()


class PipelineRules(_Section):
    """Jobs a pipeline execution must have reported before the gate decides (docs/pipelines.md)."""

    jobs: tuple[Annotated[str, Field(min_length=1)], ...] = ()


class GateConfig(_Section):
    """A complete gate definition.

    Attributes:
        not_applicable: What a rule does when its metric is n/a (zero denominator).
            ``fail`` (default) is the safe choice: "nothing was measured" is not a pass.
    """

    name: str = "quality gate"
    not_applicable: Literal["fail", "pass"] = "fail"
    coverage: CoverageRules = CoverageRules()
    execution: ExecutionRules = ExecutionRules()
    scope: Scope = Scope()
    pipeline: PipelineRules = PipelineRules()

    @property
    def needs_results(self) -> bool:
        """True when any execution rule or pipeline job is configured (then results are required)."""
        return bool(self.pipeline.jobs) or any(
            value is not None for value in self.execution.model_dump().values()
        )

    @property
    def rule_count(self) -> int:
        """Number of configured rules."""
        values = [*self.coverage.model_dump().values(), *self.execution.model_dump().values()]
        return sum(1 for value in values if value is not None)


def load_gate_config(path: Path) -> GateConfig:
    """Read and validate a gate file.

    Raises:
        GateConfigError: Unreadable file, TOML error, unknown key, out-of-range value, or a
            file that configures no rule at all (a gate that checks nothing would always pass).
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        raise GateConfigError(f"{path.name}: cannot be read ({error})") from None
    except tomllib.TOMLDecodeError as error:
        raise GateConfigError(f"{path.name}: not valid TOML ({error})") from None
    try:
        config = GateConfig.model_validate(data)
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        raise GateConfigError(f"{path.name}: {where}: {first['msg']}") from None
    if config.rule_count == 0:
        raise GateConfigError(
            f"{path.name}: configures no rule; a gate that checks nothing would always pass"
        )
    return config
