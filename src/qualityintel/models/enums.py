"""Closed value sets used across the model.

``StrEnum`` keeps the values readable in TOML/JSON files, SQLite rows and reports, while
code compares members instead of loose strings.
"""

from __future__ import annotations

from enum import StrEnum


class AutomationStatus(StrEnum):
    """How a test case is executed today."""

    AUTOMATED = "automated"
    MANUAL = "manual"
    PLANNED = "planned"  # automation agreed but not written yet
    BLOCKED = "blocked"  # cannot be automated now (missing test hook, environment, licence ...)


class TestType(StrEnum):
    """Level or channel a test case exercises."""

    __test__ = False  # not a pytest test class, despite the name

    UI = "ui"
    API = "api"
    MOBILE = "mobile"
    DATABASE = "database"
    INTEGRATION = "integration"
    PERFORMANCE = "performance"


class Outcome(StrEnum):
    """Normalised result of one test execution.

    JUnit XML distinguishes a *failure* (an assertion did not hold) from an *error* (the test
    could not run to its assertion, e.g. an exception in set-up). Both count as "not passed";
    they stay separate because they usually need different people to act.
    """

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    SKIPPED = "skipped"


class Criticality(StrEnum):
    """Business impact if the requirement is broken in production."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Priority(StrEnum):
    """Delivery priority of a requirement (independent of criticality)."""

    P1 = "p1"
    P2 = "p2"
    P3 = "p3"
    P4 = "p4"


class Risk(StrEnum):
    """Likelihood that the requirement breaks (change frequency, complexity, defect history)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
