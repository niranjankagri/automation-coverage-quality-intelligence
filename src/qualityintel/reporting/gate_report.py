"""Quality gate reports: JSON for machines, self-contained HTML for people, Markdown for CI summaries.

All three are built from one dictionary (:func:`gate_document`), so they cannot disagree.
The HTML has no scripts and no external resources (it is opened from CI artifacts, often
offline) and escapes every value: test names and failure messages are untrusted text.
"""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from importlib.resources import files
from string import Template
from typing import Any

from qualityintel import __version__
from qualityintel.gates.evaluate import GateResult, GateStatus
from qualityintel.models.enums import Outcome
from qualityintel.traceability.pipelines import PipelineExecution
from qualityintel.traceability.report import TraceabilityReport

SCHEMA_VERSION = 1
_TEMPLATE = Template(
    files("qualityintel.reporting").joinpath("templates/gate_report.html").read_text(encoding="utf-8")
)
_STATUS_TEXT = {
    GateStatus.PASSED: "PASSED",
    GateStatus.FAILED: "FAILED",
    GateStatus.INCOMPLETE: "INCOMPLETE: input missing or invalid, no decision possible",
}


def gate_document(
    result: GateResult,
    report: TraceabilityReport,
    catalog_name: str,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Everything a report shows, as JSON-ready data (stable keys, see docs/quality-gates.md)."""
    coverage = report.coverage
    counts = report.outcome_counts
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "qi", "version": __version__},
        "generated_at": (generated_at or datetime.now(UTC)).isoformat(),
        "gate": {
            "name": result.config.name,
            "status": result.status.value,
            "exit_code": result.exit_code,
            "not_applicable": result.config.not_applicable,
            "scope": result.config.scope.model_dump(),
        },
        "input_problems": list(result.input_problems),
        "pipeline": _pipeline(result.pipeline),
        "rules": [
            {
                "name": rule.name,
                "status": rule.status.value,
                "fails_gate": rule.counts_as_failure,
                "actual": rule.actual,
                "expected": rule.expected,
                "explanation": rule.explanation,
                "items": list(rule.items),
            }
            for rule in result.rules
        ],
        "metrics": {
            "requirement_coverage": _ratio(coverage.totals.requirement_coverage),
            "automation_coverage": _ratio(coverage.totals.automation_coverage),
            "automated_requirement_coverage": _ratio(coverage.totals.automated_requirement_coverage),
            "execution_pass_rate": _ratio(report.pass_rate),
            "outcomes": {outcome.value: counts[outcome] for outcome in Outcome},
        },
        "gaps": {
            "requirements_without_tests": [r.id for r in coverage.requirements_without_tests],
            "requirements_without_automation": [r.id for r in coverage.requirements_without_automation],
            "uncovered_critical": [r.id for r in coverage.uncovered_critical],
            "unlinked_automated_cases": [c.id for c in coverage.unlinked_automated_cases],
            "automated_cases_without_results": list(report.automated_cases_without_results),
            "unmatched_results": len(report.unmatched),
        },
        "failing_requirements": [
            rid for rid, status in report.requirement_status.items() if status == "failing"
        ],
        "failing_critical": list(report.failing_critical),
        "inputs": {
            "catalog": catalog_name,
            "requirements_in_scope": len(coverage.requirements),
            "runs": [
                {
                    "source": run.source,
                    "run_id": run.run_id,
                    "context": run.context.model_dump(),
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "outcomes": {o.value: n for o, n in run.outcome_counts().items()},
                }
                for run in report.snapshot
            ],
        },
    }


def _pipeline(execution: PipelineExecution | None) -> dict[str, Any] | None:
    """The pipeline execution the gate ran on (None when it was not run on one)."""
    if execution is None:
        return None
    return {
        "id": execution.pipeline_id,
        "state": execution.state.value,
        "branch": execution.branch,
        "commit": execution.commit,
        "missing_jobs": list(execution.missing),
        "jobs": [
            {
                "name": job.name,
                "attempt": job.attempt,
                "expected": job.expected,
                "runs": len(job.runs),
                "superseded_runs": len(job.superseded),
                "outcomes": {o.value: n for o, n in job.outcome_counts.items()},
            }
            for job in execution.jobs
        ],
    }


def _pipeline_line(pipeline: dict[str, Any]) -> str:
    """``pipeline 123 on main at abc: complete (3 jobs)``."""
    where = "".join(
        f" {word} {pipeline[key]}" for word, key in (("on", "branch"), ("at", "commit")) if pipeline[key]
    )
    jobs = len([job for job in pipeline["jobs"] if job["expected"]])
    missing = f", missing: {', '.join(pipeline['missing_jobs'])}" if pipeline["missing_jobs"] else ""
    return f"pipeline {pipeline['id']}{where}: {pipeline['state']} ({jobs} job(s) reported{missing})"


def _job_results(job: dict[str, Any]) -> str:
    """``120 passed, 1 failed`` (outcomes that occurred) plus attempt and extra-job notes."""
    shown = ", ".join(f"{n} {outcome}" for outcome, n in job["outcomes"].items() if n) or "no results"
    notes = [f"attempt {job['attempt']}"] if job["attempt"] > 1 else []
    if not job["expected"]:
        notes.append("not an expected job")
    return shown + (f" ({'; '.join(notes)})" if notes else "")


def to_json(document: dict[str, Any]) -> str:
    """Pretty JSON with a trailing newline."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def to_markdown(document: dict[str, Any]) -> str:
    """Short summary for a CI job page (GitHub ``$GITHUB_STEP_SUMMARY``)."""
    gate = document["gate"]
    icon = {"passed": "✅", "failed": "❌", "incomplete": "⚠️"}[gate["status"]]
    lines = [
        f"## {icon} {_md(gate['name'])}: {_STATUS_TEXT[GateStatus(gate['status'])]}",
        "",
    ]
    if document["input_problems"]:
        lines += ["**Input problems**", "", *(f"- {_md(p)}" for p in document["input_problems"]), ""]
    pipeline = document.get("pipeline")
    if pipeline:
        lines += [f"**{_md(_pipeline_line(pipeline))}**", "", "| Job | Runs | Results |", "|---|---|---|"]
        lines += [
            f"| {_md(job['name'])} | {job['runs']} | {_md(_job_results(job))} |" for job in pipeline["jobs"]
        ]
        lines += [f"| {_md(name)} | 0 | missing |" for name in pipeline["missing_jobs"]]
        lines.append("")
    lines += ["| Rule | Actual | Expected | Result |", "|---|---|---|---|"]
    for rule in document["rules"]:
        result = "fail" if rule["fails_gate"] else rule["status"]
        lines.append(f"| {_md(rule['name'])} | {_md(rule['actual'])} | {_md(rule['expected'])} | {result} |")
    failing = [rule for rule in document["rules"] if rule["fails_gate"] and rule["items"]]
    for rule in failing:
        shown = ", ".join(rule["items"][:20]) + (" ..." if len(rule["items"]) > 20 else "")
        lines += ["", f"**{_md(rule['name'])}:** {_md(shown)}"]
    metrics = document["metrics"]
    lines += [
        "",
        f"Requirement coverage {metrics['requirement_coverage']['text']} · automation coverage "
        f"{metrics['automation_coverage']['text']} · pass rate {metrics['execution_pass_rate']['text']} · "
        f"{len(document['inputs']['runs'])} run(s), catalog `{_md(document['inputs']['catalog'])}`",
    ]
    return "\n".join(lines) + "\n"


def to_html(document: dict[str, Any]) -> str:
    """Self-contained HTML report (template in ``templates/gate_report.html``, every value escaped)."""
    gate = document["gate"]
    status = gate["status"]
    metrics = document["metrics"]
    gaps = document["gaps"]
    rule_rows = "".join(
        f"<tr class='{'bad' if rule['fails_gate'] else 'ok'}'>"
        f"<td>{_h(rule['name'])}<div class='sub'>{_h(rule['explanation'])}</div></td>"
        f"<td>{_h(rule['actual'])}</td><td>{_h(rule['expected'])}</td>"
        f"<td class='result'>{'fail' if rule['fails_gate'] else _h(rule['status'])}</td>"
        f"<td>{_items(rule['items'])}</td></tr>"
        for rule in document["rules"]
    )
    cards = "".join(
        f"<div class='card'><div class='label'>{label}</div>"
        f"<div class='value'>{_h(metrics[key]['text'])}</div></div>"
        for label, key in (
            ("Requirement coverage", "requirement_coverage"),
            ("Automation coverage", "automation_coverage"),
            ("Automated requirement coverage", "automated_requirement_coverage"),
            ("Execution pass rate", "execution_pass_rate"),
        )
    )
    gap_rows = "".join(
        f"<dt>{label}</dt><dd>{value}</dd>"
        for label, value in (
            ("Critical requirements without automation", _items(gaps["uncovered_critical"])),
            ("Requirements without tests", _items(gaps["requirements_without_tests"])),
            ("Requirements without automation", _items(gaps["requirements_without_automation"])),
            ("Failing requirements", _items(document["failing_requirements"])),
            ("Automated test cases without results", _items(gaps["automated_cases_without_results"])),
            ("Results matching no test case", str(gaps["unmatched_results"])),
        )
    )
    run_rows = "".join(
        "<tr>"
        + "".join(
            f"<td>{_h(value)}</td>"
            for value in (
                run["source"],
                run["context"]["framework"] or "-",
                run["context"]["browser"] or "-",
                run["context"]["build"] or "-",
                _short_time(run["started_at"]),
                *(
                    run["outcomes"][o.value]
                    for o in (Outcome.PASSED, Outcome.FAILED, Outcome.ERROR, Outcome.SKIPPED)
                ),
            )
        )
        + "</tr>"
        for run in document["inputs"]["runs"]
    )
    problems = "".join(f"<li>{_h(p)}</li>" for p in document["input_problems"])
    inputs = document["inputs"]
    pipeline = document.get("pipeline")
    pipeline_html = ""
    if pipeline:
        job_rows = "".join(
            f"<tr><td>{_h(job['name'])}</td><td>{job['runs']}</td><td>{_h(_job_results(job))}</td></tr>"
            for job in pipeline["jobs"]
        ) + "".join(
            f"<tr class='bad'><td>{_h(name)}</td><td>0</td><td>missing</td></tr>"
            for name in pipeline["missing_jobs"]
        )
        pipeline_html = (
            f"<section><h2>Pipeline</h2><p>{_h(_pipeline_line(pipeline))}</p><div class='wrap'><table>"
            f"<thead><tr><th>Job</th><th>Runs</th><th>Results</th></tr></thead><tbody>{job_rows}</tbody>"
            "</table></div></section>"
        )
    return _TEMPLATE.substitute(
        title=_h(f"{gate['name']}: {status}"),
        status=_h(status),
        gate_name=_h(gate["name"]),
        status_text=_h(_STATUS_TEXT[GateStatus(status)]),
        meta=_h(
            f"exit code {gate['exit_code']} · generated {document['generated_at']} · "
            f"qi {document['tool']['version']}"
        ),
        problems=f"<section><h2>Input problems</h2><ul>{problems}</ul></section>" if problems else "",
        pipeline=pipeline_html,
        rule_rows=rule_rows or "<tr><td colspan='5'>no rules</td></tr>",
        cards=cards,
        gaps=gap_rows,
        inputs=f"Catalog <code>{_h(inputs['catalog'])}</code>, "
        f"{inputs['requirements_in_scope']} requirement(s) in scope. Latest run per context:",
        run_rows=run_rows or "<tr><td colspan='9'>no runs</td></tr>",
    )


def _ratio(ratio: Any) -> dict[str, Any]:
    """Ratio as numerator, denominator, percent (None = n/a) and display text."""
    return {
        "numerator": ratio.numerator,
        "denominator": ratio.denominator,
        "percent": ratio.percent,
        "text": str(ratio),
    }


def _short_time(iso: str | None) -> str:
    """``2026-10-19T07:33:02+00:00`` -> ``2026-10-19 07:33 UTC`` (stored times are UTC)."""
    return f"{iso[:16].replace('T', ' ')} UTC" if iso else "-"


def _items(items: list[str] | tuple[str, ...]) -> str:
    """Comma-separated, escaped; a dash when empty."""
    return ", ".join(_h(item) for item in items) if items else "&ndash;"


def _h(value: object) -> str:
    """HTML-escape any value (quotes included)."""
    return html.escape(str(value), quote=True)


def _md(value: object) -> str:
    """Escape characters that would break a Markdown table cell."""
    return str(value).replace("|", "\\|").replace("\n", " ")


def to_text(document: dict[str, Any]) -> str:
    """Terminal / CI log version: verdict, one line per rule, what failed."""
    gate = document["gate"]
    lines = [
        f"GATE {gate['name']}: {_STATUS_TEXT[GateStatus(gate['status'])]} (exit code {gate['exit_code']})"
    ]
    lines += [f"  input problem: {problem}" for problem in document["input_problems"]]
    pipeline = document.get("pipeline")
    if pipeline:
        lines.append(f"  {_pipeline_line(pipeline)}")
        lines += [
            f"    job {job['name']:<20} {job['runs']} run(s), {_job_results(job)}" for job in pipeline["jobs"]
        ]
    for rule in document["rules"]:
        result = "FAIL" if rule["fails_gate"] else rule["status"]
        lines.append(f"  {result:<15} {rule['name']:<42} {rule['actual']:<22} expected {rule['expected']}")
        if rule["fails_gate"] and rule["items"]:
            shown = ", ".join(rule["items"][:15]) + (" ..." if len(rule["items"]) > 15 else "")
            lines.append(f"                  {shown}")
    return "\n".join(lines) + "\n"


def incomplete_document(gate_name: str, problems: list[str], catalog_name: str) -> dict[str, Any]:
    """Report for a gate that could not even start (catalog unreadable): status incomplete."""
    empty = {"numerator": 0, "denominator": 0, "percent": None, "text": "n/a (0/0)"}
    return {
        "schema_version": SCHEMA_VERSION,
        "tool": {"name": "qi", "version": __version__},
        "generated_at": datetime.now(UTC).isoformat(),
        "gate": {
            "name": gate_name,
            "status": GateStatus.INCOMPLETE.value,
            "exit_code": 3,
            "not_applicable": "fail",
            "scope": {},
        },
        "input_problems": problems,
        "pipeline": None,
        "rules": [],
        "metrics": {
            "requirement_coverage": empty,
            "automation_coverage": empty,
            "automated_requirement_coverage": empty,
            "execution_pass_rate": empty,
            "outcomes": {outcome.value: 0 for outcome in Outcome},
        },
        "gaps": {
            "requirements_without_tests": [],
            "requirements_without_automation": [],
            "uncovered_critical": [],
            "unlinked_automated_cases": [],
            "automated_cases_without_results": [],
            "unmatched_results": 0,
        },
        "failing_requirements": [],
        "failing_critical": [],
        "inputs": {"catalog": catalog_name, "requirements_in_scope": 0, "runs": []},
    }
