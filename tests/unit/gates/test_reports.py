import json
from datetime import UTC, datetime

import pytest

from qualityintel.gates.config import GateConfig
from qualityintel.gates.evaluate import evaluate
from qualityintel.models.enums import Outcome
from qualityintel.models.results import PipelineJob
from qualityintel.reporting.gate_report import (
    gate_document,
    incomplete_document,
    to_html,
    to_json,
    to_markdown,
    to_text,
)
from qualityintel.traceability.pipelines import pipeline_execution
from qualityintel.traceability.report import build_report

from ..traceability.helpers import case, catalog, req, result, run

pytestmark = pytest.mark.unit

HOSTILE = "<script>alert('x')</script> & \"quotes\" | pipe"


def document() -> dict[str, object]:
    """A failed gate whose test name and failure message contain HTML and Markdown syntax."""
    cat = catalog([req("R1", criticality="critical")], [case("A", "R1", automated_by=("suite::*",))])
    report = build_report(
        cat, [run(result(HOSTILE, Outcome.FAILED, failure={"message": HOSTILE}), source=f"{HOSTILE}.xml")]
    )
    config = GateConfig.model_validate(
        {"name": "release <gate>", "execution": {"max_failing_critical": 0, "max_failed_tests": 0}}
    )
    return gate_document(evaluate(report, config), report, "catalog.toml", datetime(2026, 10, 20, tzinfo=UTC))


def test_json_document_has_stable_keys_and_values() -> None:
    """Machine readers rely on these keys (docs/quality-gates.md)."""
    data = json.loads(to_json(document()))

    assert set(data) == {
        "schema_version",
        "tool",
        "generated_at",
        "gate",
        "input_problems",
        "pipeline",
        "rules",
        "metrics",
        "gaps",
        "failing_requirements",
        "failing_critical",
        "inputs",
    }
    assert data["gate"]["status"] == "failed"
    assert data["gate"]["exit_code"] == 1
    assert data["failing_critical"] == ["R1"]
    assert data["metrics"]["execution_pass_rate"] == {
        "numerator": 0,
        "denominator": 1,
        "percent": 0.0,
        "text": "0.0 % (0/1)",
    }
    assert data["generated_at"] == "2026-10-20T00:00:00+00:00"
    assert [r["fails_gate"] for r in data["rules"]] == [True, True]


def test_html_escapes_every_value_and_has_no_script() -> None:
    """Test names are untrusted; the report must not run or break on them."""
    page = to_html(document())

    assert "<script>" not in page
    assert "&lt;script&gt;alert(&#x27;x&#x27;)&lt;/script&gt;" in page
    assert "release &lt;gate&gt;" in page
    assert "<link" not in page  # self-contained: no external stylesheet
    assert 'class="verdict failed"' in page


def test_markdown_escapes_table_pipes() -> None:
    """A | in a value would break the CI summary table."""
    markdown = to_markdown(document())

    assert markdown.startswith("## ❌ release <gate>: FAILED")
    assert "\\| pipe" in markdown
    assert "| failing critical requirements | 1 | <= 0 | fail |" in markdown


def test_text_lists_failed_items_under_the_rule() -> None:
    """The CI log shows what failed, not only that something failed."""
    text = to_text(document())

    assert "GATE release <gate>: FAILED (exit code 1)" in text
    assert "FAIL            failing critical requirements" in text
    assert "\n                  R1\n" in text


def test_incomplete_document_renders_in_every_format() -> None:
    """A gate that could not start still produces readable reports with exit code 3."""
    data = incomplete_document("release", ["catalog.toml: not valid TOML"], "catalog.toml")

    assert json.loads(to_json(data))["gate"]["exit_code"] == 3
    assert "INCOMPLETE" in to_text(data)
    assert "catalog.toml: not valid TOML" in to_html(data)
    assert "⚠️" in to_markdown(data)


def test_pipeline_section_is_in_every_format_and_escaped() -> None:
    """Job names come from the command line: escaped in HTML and Markdown like any other text."""
    hostile_job = run(result("A")).model_copy(
        update={"pipeline": PipelineJob(pipeline_id="9", job=HOSTILE, commit="abc")}
    )
    execution = pipeline_execution([hostile_job], "9", (HOSTILE, "ui"))
    cat = catalog([req("R1")], [case("A", "R1", automated_by=("suite::*",))])
    report = build_report(cat, execution.runs)
    config = GateConfig.model_validate({"execution": {"max_failed_tests": 0}})
    data = gate_document(evaluate(report, config, pipeline=execution), report, "catalog.toml")

    assert data["pipeline"]["state"] == "incomplete"
    assert data["pipeline"]["missing_jobs"] == ["ui"]
    page = to_html(data)
    assert "<script>" not in page
    assert "&lt;script&gt;" in page
    assert "<tr class='bad'><td>ui</td><td>0</td><td>missing</td></tr>" in page
    assert "| ui | 0 | missing |" in to_markdown(data)
    assert r"\| pipe" in to_markdown(data)
    assert "pipeline 9 at abc: incomplete (1 job(s) reported, missing: ui)" in to_text(data)
