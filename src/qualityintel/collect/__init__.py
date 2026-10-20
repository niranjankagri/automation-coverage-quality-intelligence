"""Collect test results from CI pipelines (docs/collection.md).

Downloads the result artifacts of producer repositories' workflow runs, as listed in a producers
file, and imports each run as a pipeline execution with the existing importers.
"""
