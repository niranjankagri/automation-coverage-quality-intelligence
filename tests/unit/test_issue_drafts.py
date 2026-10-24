"""Issue drafts for recurring failures: content, the pre-filled GitHub link, limits, escaping."""

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import pytest

from qualityintel.history.analysis import RecurringFailure
from qualityintel.models.enums import Outcome
from qualityintel.models.results import PipelineJob, TestRun
from qualityintel.reporting.issues import MAX_URL, Evidence, issue_draft
from qualityintel.workspace import Workspace

from .traceability.helpers import case, catalog, req, result, run

pytestmark = pytest.mark.unit

F = Outcome.FAILED
WHEN = datetime(2026, 10, 19, 9, tzinfo=UTC)


def failure(tests: tuple[str, ...] = ("suite::a",), runs: int = 3) -> RecurringFailure:
    """A recurring failure seen in ``runs`` runs."""
    return RecurringFailure(
        signature="TimeoutError: Timeout <n>ms exceeded.",
        occurrences=runs + 1,
        runs=runs,
        tests=tests,
        first_seen=datetime(2026, 10, 13, 9, tzinfo=UTC),
        last_seen=WHEN,
        recent_runs=2,
        run_ids=tuple(str(i) * 64 for i in range(runs)),
    )


def evidence(n: int, github: bool = True) -> list[Evidence]:
    """``n`` supporting runs, newest first."""
    return [
        Evidence(
            source=f"TEST-{i}.xml",
            started_at=WHEN,
            dashboard_path=f"classic/#/run/{str(i) * 64}",
            github_url=f"https://github.com/o/r/actions/runs/{1000 + i}" if github else None,
        )
        for i in range(n)
    ]


def test_the_draft_states_the_evidence_and_its_calculation() -> None:
    """Signature, counts with the 7-day figure, dates, tests, newest runs with both links."""
    draft = issue_draft(failure(), ["o/r"] * 3, evidence(3), "https://qi.example")

    assert draft.title == "Recurring test failure: TimeoutError: Timeout <n>ms exceeded."
    assert "**Failure signature:** `TimeoutError: Timeout <n>ms exceeded.`" in draft.body
    assert "Seen in **3 runs** (2 in the 7 days before the newest run), 4 occurrences" in draft.body
    assert "2026-10-13 to 2026-10-19 (UTC)" in draft.body
    assert "- `suite::a`" in draft.body
    assert (
        f"- TEST-0.xml, 2026-10-19 09:00 UTC: [dashboard](https://qi.example/classic/#/run/{'0' * 64}), "
        "[CI run](https://github.com/o/r/actions/runs/1000)"
    ) in draft.body
    assert "docs/metrics.md, Recurring failures" in draft.body


def test_one_known_repository_gets_githubs_prefilled_form_and_nothing_is_created() -> None:
    """The link opens GitHub's New issue form with exactly the draft's title and body."""
    draft = issue_draft(failure(), ["o/r"] * 3, evidence(3))

    assert draft.new_issue_url is not None
    parts = urlsplit(draft.new_issue_url)
    query = parse_qs(parts.query)
    assert (parts.scheme, parts.netloc, parts.path) == ("https", "github.com", "/o/r/issues/new")
    assert (query["title"], query["body"]) == ([draft.title], [draft.body])
    assert draft.repository == "o/r"
    assert not draft.shortened


@pytest.mark.parametrize(
    "repositories", [["o/r", "o/other", "o/r"], [None, None, None], ["o/r", None, "o/r"]]
)
def test_several_or_unknown_repositories_get_no_link(repositories: list[str | None]) -> None:
    """Only a draft whose every run belongs to one known repository can name where to file it."""
    draft = issue_draft(failure(), repositories, evidence(3))

    assert (draft.repository, draft.new_issue_url) == (None, None)
    assert draft.body


def test_a_long_draft_drops_evidence_lines_from_the_link_but_keeps_the_full_body() -> None:
    """Many long test names: the link stays below the address limit; the copyable body is complete."""
    tests = tuple(f"suite::{'very-long-test-name-' * 20}{i}" for i in range(40))
    draft = issue_draft(failure(tests, runs=40), ["o/r"] * 40, evidence(40), "https://qi.example")

    assert draft.shortened
    assert draft.new_issue_url is not None
    assert len(draft.new_issue_url) <= MAX_URL
    assert "- and 30 more" in draft.body  # the full body lists 10 tests and counts the rest


def test_imported_names_stay_text_in_the_issue() -> None:
    """A test named like a Markdown link stays in a code span; backticks cannot close it."""
    draft = issue_draft(failure(("suite::[x](https://evil.example)`",)), ["o/r"], evidence(1))

    assert "- `suite::[x](https://evil.example)'`" in draft.body


def test_suggestions_follow_the_recurring_rank_and_the_limit() -> None:
    """Workspace: two recurring causes in rank order, at most ``limit`` drafts, no link without collection."""
    job = PipelineJob(pipeline_id="1", job="test", repository="o/r")

    def failing(day: int, message: str) -> TestRun:
        return run(result("t", F, failure={"message": message, "type": "E"}), day=day).model_copy(
            update={"pipeline": job}
        )

    runs = [
        failing(10, "old"),
        failing(11, "old"),
        failing(11, "old"),
        failing(18, "new"),
        failing(19, "new"),
    ]
    workspace = Workspace(catalog([req("R1")], [case("TC", "R1", automated_by=("suite::*",))]), runs)

    drafts = workspace.issue_suggestions().drafts
    (only,) = workspace.issue_suggestions(limit=1).drafts

    assert [(d.rank, d.signature, d.recent_runs) for d in drafts] == [(1, "E: new", 2), (2, "E: old", 0)]
    assert only.signature == "E: new"
    assert drafts[0].repository == "o/r"
    assert "[CI run]" not in drafts[0].body  # no collection record, so no GitHub run link
