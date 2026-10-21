"""Global search: index, matching, ranking, filters and bounds (docs/dashboard.md, Search)."""

from datetime import UTC, date, datetime

import pytest

from qualityintel.models.collection import PipelineCollection
from qualityintel.models.enums import Outcome
from qualityintel.models.results import FailureDetails, PipelineJob, TestRun
from qualityintel.search import MAX_QUERY, Entry, QueryError, build_index, search

from .traceability.helpers import case, catalog, req, result, run

pytestmark = pytest.mark.unit


def collected(
    pipeline: str, repository: str, day: int, url: str = "https://github.com/o/r/actions/runs/1"
) -> PipelineCollection:
    """A collection record of one pipeline attempt."""
    return PipelineCollection(
        pipeline_id=pipeline,
        attempt=1,
        repository=repository,
        workflow="ci.yml",
        run_number=7,
        branch="main",
        commit="abc1234",
        conclusion="success",
        url=url,
        started_at=datetime(2026, 10, day, tzinfo=UTC),
        collected_at=datetime(2026, 10, day, 1, tzinfo=UTC),
        state="complete",
        runs=1,
        results=1,
    )


def in_pipeline(r: TestRun, pipeline: str, repository: str) -> TestRun:
    """The run as a collected pipeline job."""
    return r.model_copy(
        update={"pipeline": PipelineJob(pipeline_id=pipeline, job="ui", repository=repository)}
    )


@pytest.fixture
def index() -> tuple[Entry, ...]:
    """Two repositories, a failing test with a message, a requirement."""
    failing = result("checkout_pays_by_card", Outcome.FAILED).model_copy(
        update={"failure": FailureDetails(message="TimeoutError: card form did not load\nat line 3")}
    )
    shop = in_pipeline(run(failing, result("login"), day=18), "shop#111", "o/shop")
    notes = in_pipeline(run(result("notes_checkout_banner"), day=19), "notes#222", "o/notes")
    cat = catalog([req("SHOP-006", title="Customers can complete the checkout")], [case("TC-1", "SHOP-006")])
    records = [collected("shop#111", "o/shop", 18), collected("notes#222", "o/notes", 19, url="http://evil")]
    return build_index(cat, [shop, notes], records)


def test_results_are_grouped_by_kind_with_counts(index: tuple[Entry, ...]) -> None:
    """A word found in tests, a failure message and a requirement title appears in each group."""
    found = search(index, "checkout")

    assert found.counts["test"] == 2
    assert found.counts["requirement"] == 1
    assert {e.identifier for e in found.groups["test"]} == {
        "suite::checkout_pays_by_card",
        "suite::notes_checkout_banner",
    }
    assert found.total == sum(found.counts.values())


def test_every_word_must_match_and_case_does_not_matter(index: tuple[Entry, ...]) -> None:
    """'CARD timeout' finds the failure message, not every test with one of the words."""
    found = search(index, "CARD timeout")

    assert found.counts == {
        "repository": 0,
        "workflow": 0,
        "pipeline": 0,
        "test": 0,
        "requirement": 0,
        "failure": 1,
    }
    (failure,) = found.groups["failure"]
    assert failure.title == "TimeoutError: card form did not load"  # first line only
    assert dict(failure.params) == {"key": "suite::checkout_pays_by_card", "repository": "o/shop"}


def test_identifier_matches_rank_first(index: tuple[Entry, ...]) -> None:
    """Exact identifier, then prefix, then contained, then title only."""
    found = search(index, "shop")

    repositories = [e.identifier for e in found.groups["repository"]]
    assert repositories == ["o/shop"]
    assert [e.identifier for e in found.groups["pipeline"]] == ["shop#111"]


def test_a_github_run_id_finds_its_pipeline_with_its_link(index: tuple[Entry, ...]) -> None:
    """Run ids are part of pipeline ids; only https links are kept."""
    (pipeline,) = search(index, "111").groups["pipeline"]
    (other,) = search(index, "222").groups["pipeline"]

    assert pipeline.url == "https://github.com/o/r/actions/runs/1"
    assert other.url is None  # not https: never offered as a link
    assert dict(pipeline.params) == {"pipeline": "shop#111", "repository": "o/shop"}


def test_repository_and_date_filters_narrow_dated_entries_only(index: tuple[Entry, ...]) -> None:
    """Requirements (undated, no repository) stay; tests outside the repository or period go."""
    by_repository = search(index, "checkout", repositories=frozenset({"o/notes"}))
    by_date = search(index, "checkout", since=date(2026, 10, 19))

    assert [e.identifier for e in by_repository.groups["test"]] == ["suite::notes_checkout_banner"]
    assert by_repository.counts["requirement"] == 1
    assert [e.identifier for e in by_date.groups["test"]] == ["suite::notes_checkout_banner"]


def test_results_are_bounded_but_counted(index: tuple[Entry, ...]) -> None:
    """At most ``limit`` shown per group; the count says how many matched."""
    found = search(index, "suite", limit=1)

    assert len(found.groups["test"]) == 1
    assert found.counts["test"] == 3


@pytest.mark.parametrize("query", ["", "a", "  b  ", "x" * (MAX_QUERY + 1)])
def test_queries_outside_the_length_limits_are_refused(index: tuple[Entry, ...], query: str) -> None:
    """2 to 100 characters after trimming."""
    with pytest.raises(QueryError):
        search(index, query)
