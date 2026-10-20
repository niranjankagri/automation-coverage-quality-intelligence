import json
from pathlib import Path
from typing import Any

import pytest

from qualityintel.ingest.allure import is_allure_folder, read_allure_folder
from qualityintel.ingest.errors import MalformedResultError, UnsupportedFormatError
from qualityintel.models.enums import Outcome
from qualityintel.models.results import RunContext

pytestmark = pytest.mark.unit


def result(
    name: str, status: str, history: str | None = None, start: int = 1_792_418_963_000, **fields: Any
) -> dict[str, Any]:
    """An Allure 2 result entry for a TestNG test of com.example.LoginTest."""
    return {
        "uuid": f"u-{name}-{start}",
        "historyId": history or f"h-{name}",
        "name": name,
        "fullName": f"com.example.LoginTest.{name}",
        "status": status,
        "statusDetails": {},
        "labels": [
            {"name": "testClass", "value": "com.example.LoginTest"},
            {"name": "testMethod", "value": name},
            {"name": "framework", "value": "testng"},
            {"name": "suite", "value": "Regression"},
            {"name": "host", "value": "build-agent-7"},
        ],
        "links": [],
        "parameters": [],
        "start": start,
        "stop": start + 1500,
        **fields,
    }


def folder(tmp_path: Path, *entries: dict[str, Any], environment: str | None = None) -> Path:
    """An allure-results folder with these results (and optional environment.properties)."""
    path = tmp_path / "allure-results"
    path.mkdir(parents=True)
    for i, entry in enumerate(entries):
        (path / f"{i:04d}-result.json").write_text(json.dumps(entry), encoding="utf-8")
    (path / "0000-container.json").write_text("{}", encoding="utf-8")
    (path / "0000-attachment.txt").write_text("password=hunter2", encoding="utf-8")
    if environment is not None:
        (path / "environment.properties").write_text(environment, encoding="utf-8")
    return path


def test_statuses_keys_durations_and_failures(tmp_path: Path) -> None:
    """Broken = error; the key equals the JUnit key of the same TestNG test."""
    run = read_allure_folder(
        folder(
            tmp_path,
            result("logsIn", "passed"),
            result(
                "rejectsBadPassword",
                "failed",
                statusDetails={"message": "expected 401", "trace": "at LoginTest.java:42"},
            ),
            result("usesExpiredToken", "broken", statusDetails={"message": "NullPointerException"}),
            result("needsTwoFactor", "skipped"),
        )
    ).run

    by_name = {r.name: r for r in run.results}
    assert {n: r.outcome for n, r in by_name.items()} == {
        "logsIn": Outcome.PASSED,
        "rejectsBadPassword": Outcome.FAILED,
        "usesExpiredToken": Outcome.ERROR,
        "needsTwoFactor": Outcome.SKIPPED,
    }
    failed = by_name["rejectsBadPassword"]
    assert failed.key == "com.example.LoginTest::rejectsBadPassword"
    assert failed.duration_seconds == 1.5
    assert failed.suite == "Regression"
    assert failed.failure is not None
    assert (failed.failure.message, failed.failure.text) == ("expected 401", "at LoginTest.java:42")
    assert run.context == RunContext(framework="testng")
    assert run.started_at is not None


def test_unknown_status_is_an_error_with_a_warning(tmp_path: Path) -> None:
    """'unknown' must neither pass nor vanish."""
    parsed = read_allure_folder(folder(tmp_path, result("odd", "unknown")))

    assert parsed.run.results[0].outcome is Outcome.ERROR
    assert parsed.warnings == ("odd: Allure status 'unknown' counted as error",)


def test_attempts_with_the_same_history_id_are_one_test_with_retries(tmp_path: Path) -> None:
    """Failed, then passed on the retry: one passed result with retries = 1."""
    run = read_allure_folder(
        folder(
            tmp_path,
            result("flaky", "failed", history="h1", start=1000),
            result("flaky", "passed", history="h1", start=5000),
        )
    ).run

    (only,) = run.results
    assert only.outcome is Outcome.PASSED
    assert only.passed_after_retry


def test_parameters_ids_and_fallback_key(tmp_path: Path) -> None:
    """Parameters are appended; AS_ID and tms links become explicit ids; no labels -> fullName."""
    entry = result(
        "signsIn",
        "passed",
        parameters=[{"name": "user", "value": "admin"}],
        links=[{"type": "tms", "name": "TC-7"}],
    )
    entry["labels"].append({"name": "AS_ID", "value": "TC-1"})
    bare = result("bare", "passed")
    bare["labels"] = []

    run = read_allure_folder(folder(tmp_path, entry, bare)).run

    by_name = {r.name: r for r in run.results}
    assert by_name["signsIn[admin]"].test_ids == ("TC-1", "TC-7")
    assert by_name["bare"].classname == "com.example.LoginTest"


@pytest.mark.parametrize(
    ("properties", "build"),
    [
        ("build=1.4.2\ngit.commit=abc\nbuild.number=41\n", "1.4.2"),
        ("git.commit=abc\nbuild.number=41\n", "abc"),
        ("build.number=41\n", "41"),
    ],
)
def test_context_from_environment_properties(tmp_path: Path, properties: str, build: str) -> None:
    """Browser and environment as given; build prefers build, then the commit, then the CI counter."""
    run = read_allure_folder(
        folder(
            tmp_path,
            result("a", "passed"),
            environment="browser=firefox\nenvironment=staging\ndatabase=jdbc:secret\n" + properties,
        )
    ).run

    assert run.context == RunContext(
        framework="testng", browser="firefox", environment="staging", build=build
    )


def test_machine_names_attachments_and_containers_are_not_imported(tmp_path: Path) -> None:
    """Host labels, attachment contents and fixture containers stay out of the model."""
    run = read_allure_folder(folder(tmp_path, result("a", "passed"))).run

    dump = run.model_dump_json()
    assert "build-agent-7" not in dump
    assert "hunter2" not in dump


def test_folder_detection_and_errors(tmp_path: Path) -> None:
    """Only folders with *-result.json are Allure; broken files name themselves."""
    empty = tmp_path / "empty"
    empty.mkdir()
    assert not is_allure_folder(empty)
    with pytest.raises(UnsupportedFormatError, match="not an Allure results folder"):
        read_allure_folder(empty)

    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "x-result.json").write_text("{oops", encoding="utf-8")
    assert is_allure_folder(broken)
    with pytest.raises(MalformedResultError, match=r"x-result\.json is not valid JSON"):
        read_allure_folder(broken)

    nameless = tmp_path / "nameless"
    nameless.mkdir()
    (nameless / "y-result.json").write_text('{"status": "passed"}', encoding="utf-8")
    with pytest.raises(MalformedResultError, match=r"y-result\.json has no name or status"):
        read_allure_folder(nameless)


def test_same_folder_content_gives_the_same_run_id(tmp_path: Path) -> None:
    """Duplicate imports of a results folder are detected like duplicate files."""
    first = read_allure_folder(folder(tmp_path / "a", result("a", "passed")))
    second = read_allure_folder(folder(tmp_path / "b", result("a", "passed")))

    assert first.run.run_id == second.run.run_id


def test_repeated_invocations_count_every_time_and_only_failed_attempts_are_retries(tmp_path: Path) -> None:
    """TestNG invocationCount: 4 passes of one method are 4 executions, not 1 test with 3 retries."""
    four = [result("everyThread", "passed", history="h", start=1000 + i) for i in range(4)]
    retried = [
        result("flaky", "failed", history="f", start=1000),
        result("flaky", "passed", history="f", start=2000),
    ]
    twice_failed = [
        result("broken", "failed", history="b", start=1000),
        result("broken", "failed", history="b", start=2000),
    ]
    passed_then_failed = [
        result("p", "passed", history="p", start=1000),
        result("p", "failed", history="p", start=2000),
    ]

    run = read_allure_folder(folder(tmp_path, *four, *retried, *twice_failed, *passed_then_failed)).run

    outcomes = sorted((r.name, r.outcome.value, r.retries) for r in run.results)
    assert outcomes == [
        ("broken", "failed", 1),
        ("everyThread", "passed", 0),
        ("everyThread", "passed", 0),
        ("everyThread", "passed", 0),
        ("everyThread", "passed", 0),
        ("flaky", "passed", 1),
        ("p", "failed", 0),
        ("p", "passed", 0),
    ]
