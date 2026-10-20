"""Renderers that turn analysis results into text, JSON and HTML.

Renderers only format: every number they print is computed in ``traceability``, ``history``
or ``gates``. Keeping them apart lets the CLI, the CI report and the dashboard show the same
values without recomputing them.
"""
