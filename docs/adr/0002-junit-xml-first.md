# ADR 0002: JUnit XML is the first and common input format

Status: Accepted (2026-10-20)

## Context

The results to import come from Selenium/TestNG (Maven Surefire), Playwright (Java and
TypeScript), pytest, Cypress, Appium/TestNG and Robot Framework. Their native reports differ.

## Decision

Support JUnit XML first. Surefire, Playwright Test, pytest and Cypress (with a reporter) write
it directly; Robot Framework writes it with `--xunit`. Write a framework-specific adapter only
when a framework's JUnit XML lacks information the model needs, or the framework cannot write
JUnit XML at all.

JUnit XML has no single official schema; producers differ (nesting of `testsuite`, `error`
vs `failure`, timestamps, `file` attributes). The importer is tested against real files from
each framework it claims to support, and the README lists only frameworks with such a test.

## Consequences

- One parser covers most frameworks.
- Some details are lost compared with native reports (for example, Playwright attachments).
  Those are out of scope; the platform links to the framework's own report instead.
- Support claims are backed by test files, not by "it is JUnit XML, so it should work".
