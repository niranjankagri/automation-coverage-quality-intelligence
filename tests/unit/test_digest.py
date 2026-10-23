"""The daily digest: one day's runs, gate, regressions, changed tests and recurring failures."""

from datetime import date

import pytest

from qualityintel.gates.config import GateConfig
from qualityintel.models.enums import Outcome
from qualityintel.models.results import PipelineJob, TestRun
from qualityintel.reporting.digest import dashboard_link, render_digest
from qualityintel.workspace import DigestLine, DigestView, Workspace

from .traceability.helpers import case, catalog, req, result, run

pytestmark = pytest.mark.unit

P, F = Outcome.PASSED, Outcome.FAILED
CATALOG = catalog([req("R1")], [case("TC", "R1", automated_by=("suite::*",))])


def collected(day: int, *outcomes: tuple[str, Outcome], build: str = "", repository: str = "o/a") -> TestRun:
    """A run of job 'test' in ``repository`` on 2026-10-<day>; failures share one message."""
    job = PipelineJob(pipeline_id=f"{repository}-{day}-{build}", job="test", repository=repository)
    results = (
        result(n, o, failure={"message": "boom", "type": "E"} if o is F else None) for n, o in outcomes
    )
    made = run(*results, day=day, build=build) if build else run(*results, day=day)
    return made.model_copy(update={"pipeline": job})


def lines(view: DigestView, title: str) -> list[DigestLine]:
    """The lines of one section."""
    (section,) = [s for s in view.sections if s.title == title]
    return list(section.lines)


def test_default_day_is_the_newest_with_runs_and_previous_skips_days_without_runs() -> None:
    """Runs on 10 and 14 Oct: the digest is of the 14th, compared with the 10th (not the 13th)."""
    view = Workspace(CATALOG, [collected(10, ("x", P)), collected(14, ("x", P))]).digest()

    assert (view.day, view.previous_day) == (date(2026, 10, 14), date(2026, 10, 10))
    assert lines(view, "Runs")[0].text == "1 run(s), 1 results, 0 failed or errored"
    assert lines(view, "Runs")[0].params == {"since": "2026-10-14", "until": "2026-10-14"}


def test_a_day_without_runs_says_so_and_has_no_sections() -> None:
    """Nothing is invented for a day nothing ran."""
    view = Workspace(CATALOG, [collected(10, ("x", P))]).digest(day=date(2026, 10, 11))

    assert view.sections == ()
    assert view.notes == ("no dated run in this scope on 2026-10-11",)


def test_later_runs_do_not_change_the_digest_of_an_earlier_day() -> None:
    """The digest of the 10th sees nothing of the 12th."""
    runs = [collected(10, ("x", P)), collected(12, ("x", F))]

    view = Workspace(CATALOG, runs).digest(day=date(2026, 10, 10))

    assert lines(view, "Runs")[0].text.endswith("0 failed or errored")
    assert lines(view, "Tests that changed")[0].text == "no earlier day with runs to compare with"


def test_tests_that_started_failing_are_listed_per_repository_with_links() -> None:
    """o/a: x fails on the 12th after passing on the 10th; runs without a repository are their own group."""
    runs = [collected(10, ("x", P)), collected(12, ("x", F)), run(result("y", F), day=12)]

    found = lines(Workspace(CATALOG, runs).digest(), "Tests that changed")

    assert [(line.text, line.route) for line in found] == [
        ("o/a: 1 started failing, 0 stopped failing", "/trends"),
        ("o/a: started failing: suite::x", "/test"),
        ("repository not recorded: 1 started failing, 0 stopped failing", "/trends"),
        ("repository not recorded: started failing: suite::y", "/test"),
    ]
    assert found[1].params == {"key": "suite::x"}


def test_a_regression_appears_on_the_day_of_its_newest_build_only() -> None:
    """Build b2 (12th) fails x that b1 (10th) passed: in the digest of the 12th, linked to Compare."""
    runs = [collected(10, ("x", P), build="b1"), collected(12, ("x", F), build="b2")]
    workspace = Workspace(CATALOG, runs)

    (line,) = lines(workspace.digest(), "Regressions")
    (none,) = lines(workspace.digest(day=date(2026, 10, 10)), "Regressions")

    assert line.text == "-/-/-/- (test): 1 test(s) newly failing, build b1 -> b2"
    assert (line.route, line.params) == ("/compare", {"base": "b1", "head": "b2"})
    assert none.route is None


def test_recurring_failures_seen_that_day_link_their_newest_run() -> None:
    """The same cause on the 11th and 12th is recurring and seen again on the 12th."""
    runs = [collected(11, ("x", F)), collected(12, ("x", F))]

    (line,) = lines(Workspace(CATALOG, runs).digest(), "Recurring failures seen again")

    assert line.text == "E: boom: 2 runs, 2 in the 7 days before 2026-10-12"
    assert line.route == f"/run/{runs[1].run_id}"


def test_the_gate_section_compares_the_verdict_with_the_previous_day() -> None:
    """With a gate: passed on the 10th, failed on the 12th, and the rule that started failing."""
    gate = GateConfig.model_validate({"name": "release", "execution": {"min_pass_rate": 100}})
    runs = [collected(10, ("x", P)), collected(12, ("x", F))]

    found = lines(Workspace(CATALOG, runs, gate=gate).digest(), "Release gate")
    without = Workspace(CATALOG, runs).digest()

    assert found[0].text == "release: failed (failing: execution pass rate); passed on 2026-10-10"
    assert found[1].text == "changed from passed to failed; started failing: execution pass rate"
    assert "Release gate" not in [s.title for s in without.sections]


def test_links_are_relative_or_under_the_given_base_url() -> None:
    """``#/route?params`` by default; absolute with a base URL; none for a line without evidence."""
    line = DigestLine(text="t", route="/test", params={"key": "suite::a b"})

    assert dashboard_link(line) == "/#/test?key=suite%3A%3Aa+b"
    assert dashboard_link(line, "https://qi.example/") == "https://qi.example/#/test?key=suite%3A%3Aa+b"
    assert dashboard_link(DigestLine(text="t", route=None, params={})) is None


def test_imported_names_stay_text_in_markdown() -> None:
    """A test named like a Markdown link is escaped, the dashboard link still works."""
    runs = [collected(10, ("[x](https://evil.example)", P)), collected(12, ("[x](https://evil.example)", F))]

    made = render_digest(Workspace(CATALOG, runs).digest())

    assert "](https://evil.example)" not in made.markdown
    assert "\\[x\\]\\(https://evil.example\\)" in made.markdown
    assert made.text.startswith("Quality digest 2026-10-12 (compared with 2026-10-10)\n")
