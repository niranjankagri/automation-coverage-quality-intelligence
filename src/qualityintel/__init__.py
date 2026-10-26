"""Automation Coverage & Quality Intelligence.

Imports results from existing test automation frameworks, links them to requirements,
measures coverage, analyses execution history and decides release quality gates.

Layers (see docs/architecture.md):

- ``models``: typed data model shared by every other layer.
- ``ingest``: reads result files (JUnit XML first) into the model.
- ``traceability``: requirement-to-test mapping and coverage metrics.
- ``history``: SQLite execution history, trends and flaky-test candidates.
- ``gates``: configurable release criteria and JSON/HTML reports.
- ``dashboard``: thin web layer over the packages above; nothing else imports it.
"""

__version__ = "1.2.1"
