"""Gate configuration and evaluation: every rule passing, failing and not applicable."""

from pathlib import Path

import pytest

from qualityintel.gates.config import GateConfig, GateConfigError, load_gate_config
from qualityintel.gates.evaluate import GateStatus, RuleResult, RuleStatus, evaluate
from qualityintel.models.catalog import Catalog
from qualityintel.models.enums import Outcome
from qualityintel.models.results import PipelineJob
from qualityintel.traceability.coverage import Filters
from qualityintel.traceability.pipelines import pipeline_execution
from qualityintel.traceability.report import build_report

from ..traceability.helpers import case, catalog, req, result, run

pytestmark = pytest.mark.unit


def config(**sections: object) -> GateConfig:
    """Gate config built from keyword sections such as execution={"min_pass_rate": 95}."""
    return GateConfig.model_validate(sections)


@pytest.fixture
def shop() -> Catalog:
    """R1 critical automated (A), R2 critical planned only, R3 high automated (B)."""
    return catalog(
        [req("R1", criticality="critical"), req("R2", criticality="critical"), req("R3", criticality="high")],
        [case("A", "R1"), case("P", "R2", status="planned"), case("B", "R3")],
    )


def rule(result_rules: list[RuleResult], name: str) -> RuleResult:
    """The rule with this name from a gate result."""
    return next(r for r in result_rules if r.name == name)


# ---- configuration ---------------------------------------------------------------------------


def test_config_file_loads_with_defaults(tmp_path: Path) -> None:
    """Only configured rules are set; n/a fails by default."""
    path = tmp_path / "gate.toml"
    path.write_text('name = "release"\n[execution]\nmin_pass_rate = 95\n', encoding="utf-8")

    loaded = load_gate_config(path)

    assert loaded.name == "release"
    assert loaded.execution.min_pass_rate == 95
    assert loaded.coverage.min_requirement_coverage is None
    assert loaded.not_applicable == "fail"
    assert loaded.needs_results
    assert loaded.rule_count == 1


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[execution]\nmin_pass_rat = 95", r"execution\.min_pass_rat: Extra inputs are not permitted"),
        (
            "[execution]\nmin_pass_rate = 120",
            r"execution\.min_pass_rate: Input should be less than or equal to 100",
        ),
        ("[coverage]\nmax_uncovered_critical = -1", r"coverage\.max_uncovered_critical"),
        ('not_applicable = "ignore"\n[execution]\nmin_pass_rate = 1', r"not_applicable"),
        ('name = "empty gate"', r"configures no rule"),
        ("[execution\n", r"not valid TOML"),
    ],
    ids=["typo", "over-100", "negative", "bad-na-mode", "no-rules", "toml"],
)
def test_bad_config_is_rejected_with_the_reason(tmp_path: Path, text: str, message: str) -> None:
    """A typo must not silently switch a rule off; a gate with no rules is refused."""
    path = tmp_path / "gate.toml"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(GateConfigError, match=message):
        load_gate_config(path)


def test_missing_config_file_is_an_error(tmp_path: Path) -> None:
    """Unreadable file: GateConfigError naming the file."""
    with pytest.raises(GateConfigError, match=r"gone\.toml: cannot be read"):
        load_gate_config(tmp_path / "gone.toml")


# ---- coverage rules ------------------------------------------------------------------------


def test_coverage_rules_pass_and_fail_on_the_exact_threshold(shop: Catalog) -> None:
    """2 of 3 requirements automated = 66.7 %: >= 66 passes, >= 67 fails (unrounded value)."""
    report = build_report(shop, [])

    passing = evaluate(report, config(coverage={"min_automated_requirement_coverage": 66}))
    failing = evaluate(report, config(coverage={"min_automated_requirement_coverage": 66.7}))

    assert passing.status is GateStatus.PASSED
    assert failing.status is GateStatus.FAILED
    assert rule(failing.rules, "automated requirement coverage").actual == "66.7 % (2/3)"


def test_uncovered_critical_rule_names_the_requirements(shop: Catalog) -> None:
    """R2 is critical and only planned: listed as the reason for the failure."""
    result = evaluate(build_report(shop, []), config(coverage={"max_uncovered_critical": 0}))

    failed = rule(result.rules, "critical requirements without automation")
    assert failed.status is RuleStatus.FAILED
    assert failed.items == ("R2",)
    assert result.exit_code == 1


def test_coverage_only_gate_needs_no_results(shop: Catalog) -> None:
    """A catalog gate without execution rules is complete without result files."""
    result = evaluate(build_report(shop, []), config(coverage={"min_requirement_coverage": 100}))

    assert result.status is GateStatus.PASSED
    assert result.input_problems == []


def test_requirements_without_tests_rule() -> None:
    """Counts requirements with no test case at all."""
    report = build_report(catalog([req("R1"), req("R2")], [case("A", "R1")]), [])

    result = evaluate(report, config(coverage={"max_requirements_without_tests": 0}))

    assert rule(result.rules, "requirements without tests").items == ("R2",)


# ---- execution rules -----------------------------------------------------------------------


def test_execution_rules_on_a_failing_critical_test(shop: Catalog) -> None:
    """A fails (critical R1), B passes: pass rate 50 %, one failing critical requirement."""
    report = build_report(shop, [run(result("A", Outcome.FAILED), result("B"))])

    gate = evaluate(
        report,
        config(
            execution={
                "min_pass_rate": 50,
                "max_failing_critical": 0,
                "max_failing_requirements": 1,
                "max_failed_tests": 0,
                "min_results": 2,
            }
        ),
    )

    statuses = {r.name: r.status for r in gate.rules}
    assert statuses == {
        "execution pass rate": RuleStatus.PASSED,
        "failing critical requirements": RuleStatus.FAILED,
        "failing requirements": RuleStatus.PASSED,
        "failed tests": RuleStatus.FAILED,
        "executed tests": RuleStatus.PASSED,
    }
    assert rule(gate.rules, "failed tests").items == ("suite::A",)
    assert gate.status is GateStatus.FAILED


def test_too_few_executed_tests_fail_the_gate(shop: Catalog) -> None:
    """A suite that silently ran 2 instead of 200 tests is caught."""
    report = build_report(shop, [run(result("A"), result("B"))])

    gate = evaluate(report, config(execution={"min_results": 200}))

    assert rule(gate.rules, "executed tests").actual == "2"
    assert gate.status is GateStatus.FAILED


def test_automated_cases_without_results_rule(shop: Catalog) -> None:
    """B never ran: the case is named."""
    report = build_report(shop, [run(result("A"))])

    gate = evaluate(report, config(execution={"max_automated_cases_without_results": 0}))

    assert rule(gate.rules, "automated test cases without results").items == ("B",)


# ---- missing or empty input ------------------------------------------------------------------


def test_execution_rules_without_results_are_incomplete_not_passed(shop: Catalog) -> None:
    """No result files at all: exit code 3, whatever the other rules say."""
    gate = evaluate(build_report(shop, []), config(execution={"max_failing_critical": 0}))

    assert gate.status is GateStatus.INCOMPLETE
    assert gate.exit_code == 3
    assert gate.input_problems == ["execution rules are configured but no test results were read"]


def test_results_with_zero_tests_are_incomplete(shop: Catalog) -> None:
    """A result file with no test cases (e.g. the suite crashed before collecting) is not a pass."""
    report = build_report(shop, [run(day=19)])

    gate = evaluate(report, config(execution={"max_failing_critical": 0}))

    assert gate.status is GateStatus.INCOMPLETE
    assert gate.input_problems == ["the result files contain no test results"]


def test_any_input_problem_makes_the_gate_incomplete(shop: Catalog) -> None:
    """One unreadable file next to good ones: incomplete, even if every rule passes."""
    report = build_report(shop, [run(result("A"), result("B"))])

    gate = evaluate(report, config(execution={"min_pass_rate": 0}), ["broken.xml: not well-formed XML"])

    assert all(not r.counts_as_failure for r in gate.rules)
    assert gate.status is GateStatus.INCOMPLETE


@pytest.mark.parametrize(("mode", "expected"), [("fail", GateStatus.FAILED), ("pass", GateStatus.PASSED)])
def test_not_applicable_metrics_follow_the_configuration(mode: str, expected: GateStatus) -> None:
    """Only skipped tests: pass rate n/a. Default 'fail'; 'pass' must be chosen explicitly."""
    report = build_report(catalog([req("R1")], [case("A", "R1")]), [run(result("A", Outcome.SKIPPED))])

    gate = evaluate(report, config(not_applicable=mode, execution={"min_pass_rate": 90}))

    assert rule(gate.rules, "execution pass rate").status is RuleStatus.NOT_APPLICABLE
    assert gate.status is expected


def test_empty_scope_coverage_is_not_applicable() -> None:
    """A scope with no requirements: coverage rules are n/a and fail by default."""
    report = build_report(catalog([req("R1", criticality="low")], []), [], None)
    scoped = build_report(
        catalog([req("R1", criticality="low")], []), [], Filters(criticalities=frozenset({"critical"}))
    )

    assert evaluate(report, config(coverage={"min_requirement_coverage": 0})).status is GateStatus.PASSED
    assert evaluate(scoped, config(coverage={"min_requirement_coverage": 0})).status is GateStatus.FAILED


def test_pipeline_jobs_are_read_and_typos_are_refused(tmp_path: Path) -> None:
    """[pipeline] jobs makes results required; an unknown key there is an error."""
    path = tmp_path / "gate.toml"
    path.write_text(
        '[pipeline]\njobs = ["api", "ui"]\n[coverage]\nmin_requirement_coverage = 1\n', encoding="utf-8"
    )
    loaded = load_gate_config(path)

    assert loaded.pipeline.jobs == ("api", "ui")
    assert loaded.needs_results
    path.write_text('[pipeline]\njob = ["api"]\n[coverage]\nmin_requirement_coverage = 1\n', encoding="utf-8")
    with pytest.raises(GateConfigError, match=r"pipeline\.job: Extra inputs are not permitted"):
        load_gate_config(path)


def test_an_incomplete_pipeline_never_passes_even_if_every_rule_does(shop: Catalog) -> None:
    """Passing API results of a pipeline whose UI job is missing: incomplete, exit 3."""
    api = run(result("A")).model_copy(update={"pipeline": PipelineJob(pipeline_id="9", job="api")})
    execution = pipeline_execution([api], "9", ("api", "ui"))

    gate = evaluate(
        build_report(shop, execution.runs), config(execution={"min_pass_rate": 0}), pipeline=execution
    )

    assert all(not r.counts_as_failure for r in gate.rules)
    assert gate.status is GateStatus.INCOMPLETE
    assert gate.input_problems == [
        "pipeline 9: job ui reported no results (not run, cancelled or interrupted)"
    ]
    assert gate.pipeline is execution
