"""Typed data model: requirements, test cases, mappings and execution results.

Every other layer speaks in these types, so ingestion, analysis and the dashboard
never pass raw dictionaries or file formats between each other.
"""

from qualityintel.models.catalog import Catalog, CatalogError, Requirement, TestCase, TraceLink
from qualityintel.models.enums import AutomationStatus, Criticality, Outcome, Priority, Risk, TestType
from qualityintel.models.metrics import Ratio, execution_pass_rate
from qualityintel.models.results import FailureDetails, RunContext, TestResult, TestRun

__all__ = [
    "AutomationStatus",
    "Catalog",
    "CatalogError",
    "Criticality",
    "FailureDetails",
    "Outcome",
    "Priority",
    "Ratio",
    "Requirement",
    "Risk",
    "RunContext",
    "TestCase",
    "TestResult",
    "TestRun",
    "TestType",
    "TraceLink",
    "execution_pass_rate",
]
