import pytest

from qualityintel.traceability.matching import match_results, pattern_matches

from .helpers import case, catalog, req, result, run

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("pattern", "key", "expected"),
    [
        (
            "tests.api.test_notes::test_create_note_*",
            "tests.api.test_notes::test_create_note_in_each_category[Home]",
            True,
        ),
        ("tests.api.test_notes::test_create_note_*", "tests.api.test_notes::test_get_note_by_id", False),
        # Brackets are literal: in fnmatch "[Home]" would be a character class
        ("t::test_x[Home]", "t::test_x[Home]", True),
        ("t::test_x[Home]", "t::test_xH", False),
        ("t::test_?", "t::test_a", True),
        ("t::test_?", "t::test_ab", False),
        # The whole key must match, not a part of it
        ("t::test", "t::test_more", False),
        ("*Login*", "ui/login.spec.ts::Login \u203a customer can log in", True),
        ("Case::Name", "case::name", False),
    ],
    ids=[
        "prefix",
        "other-test",
        "literal-brackets",
        "brackets-not-class",
        "question",
        "question-one-char",
        "full-match",
        "unicode",
        "case-sensitive",
    ],
)
def test_patterns_know_only_star_and_question_mark(pattern: str, key: str, expected: bool) -> None:
    """* and ? are wildcards; everything else, including [ ], is literal."""
    assert pattern_matches(pattern, key) is expected


def test_results_go_to_the_cases_whose_patterns_match() -> None:
    """Each result lands in the case its key matches; others are unmatched."""
    cat = catalog([req("R1")], [case("TC-1", "R1"), case("TC-2", "R1")])
    matching = match_results(cat, [run(result("TC-1 a"), result("TC-1 b"), result("TC-2"), result("orphan"))])

    assert [e.result.name for e in matching.by_case["TC-1"]] == ["TC-1 a", "TC-1 b"]
    assert [e.result.name for e in matching.by_case["TC-2"]] == ["TC-2"]
    assert [e.result.name for e in matching.unmatched] == ["orphan"]


def test_one_result_may_belong_to_several_cases() -> None:
    """Two cases claiming the same test both get it (visible, not hidden)."""
    cat = catalog(
        [req("R1")],
        [case("A", "R1", automated_by=("suite::shared",)), case("B", "R1", automated_by=("suite::*",))],
    )

    matching = match_results(cat, [run(result("shared"))])

    assert len(matching.by_case["A"]) == len(matching.by_case["B"]) == 1


def test_explicit_id_wins_over_patterns() -> None:
    """A result naming TC-2 goes only to TC-2, even if TC-1's pattern matches its key."""
    cat = catalog([req("R1")], [case("TC-1", "R1", automated_by=("suite::*",)), case("TC-2", "R1")])

    matching = match_results(cat, [run(result("anything", test_ids=("TC-2",)))])

    assert matching.by_case["TC-1"] == []
    assert len(matching.by_case["TC-2"]) == 1


def test_unknown_explicit_ids_are_counted_and_patterns_still_apply() -> None:
    """An id that is not in the catalog is reported; the result is matched by pattern instead."""
    cat = catalog([req("R1")], [case("TC-1", "R1")])

    matching = match_results(
        cat, [run(result("TC-1 x", test_ids=("TC-99",)), result("y", test_ids=("TC-99",)))]
    )

    assert matching.unknown_ids == {"TC-99": 2}
    assert len(matching.by_case["TC-1"]) == 1
    assert [e.result.name for e in matching.unmatched] == ["y"]


def test_automated_cases_without_results_are_listed() -> None:
    """Automated cases nothing ran for are reported; manual cases are not expected to run."""
    cat = catalog([req("R1")], [case("TC-1", "R1"), case("TC-2", "R1"), case("TC-3", "R1", status="manual")])

    matching = match_results(cat, [run(result("TC-1"))])

    assert matching.automated_cases_without_results(cat) == ["TC-2"]


def test_results_of_several_runs_are_kept_with_their_run() -> None:
    """Each execution remembers its run, so history and reports can name the build."""
    cat = catalog([req("R1")], [case("TC-1", "R1")])
    first, second = run(result("TC-1"), day=18, build="b1"), run(result("TC-1"), day=19, build="b2")

    matching = match_results(cat, [first, second])

    assert [e.run.context.build for e in matching.by_case["TC-1"]] == ["b1", "b2"]
