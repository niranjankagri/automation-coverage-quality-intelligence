# Clean-checkout validation

Can a new developer reproduce everything from the README, with nothing from my machine? This page
records how that was checked, where, and what it found. It is repeated by CI on every push.

## Manual run, 20 Oct 2026

**Environment:** Windows 11 Home (build 26300), Python 3.13.14 (python.org), Git for Windows,
Windows long paths **disabled** (registry `LongPathsEnabled = 0`, the default). Repository at
release 1.0.0 plus the README fixes below. Fresh `git clone` into an empty folder each time; no
local files, settings or environment variables from the development checkout.

| # | Step (exactly as in the README) | Shell | Result |
|---|---|---|---|
| 1 | `git clone …`, `python -m venv .venv`, activate, `pip install -e .` | cmd.exe | installed; `qi version` → `qi 1.0.0` |
| 2 | `python tools\demo.py` | cmd.exe | `10 of 10 steps behaved as documented`, exit code 0, about 9 s |
| 3 | `qi gate … nightly.toml samples/results` | cmd.exe | exit code 0 (passed) |
| 4 | `qi gate … release.toml samples/results` | cmd.exe | exit code 1 (failed: `SHOP-008`, `ADMIN-012`) |
| 5 | `qi gate … nightly.toml no-results` | cmd.exe | exit code 3 (incomplete) |
| 6 | `qi inspect "samples/results/testng-enterprise-regression-firefox/2026-10-13*"` (quoted pattern) | cmd.exe | one run, `99.2 % (120/121)`: the real 13 Oct failure |
| 7 | `qi dashboard --catalog samples/catalog.toml --database demo-output/quality.db` | Git Bash | `/api/health` → 42 requirements, 43 runs; `/api/summary` → `90.5 % (38/42)`, `86.0 % (37/43)`, `100.0 % (221/221)`; `/` → 200 |
| 8 | `pip install -e ".[dev,e2e]"`, `playwright install chromium` | Git Bash | installed (short folder, see finding 2) |
| 9 | `ruff check .`, `ruff format --check .`, `mypy` | Git Bash | no findings; 73 files type-checked |
| 10 | `pytest --cov` | Git Bash | 503 passed, branch coverage 98.44 % |
| 11 | `pytest -m e2e` | Git Bash | 13 passed (Chromium) |
| 12 | `git status` after all steps | Git Bash | clean: no command changes tracked files |

Coverage values were checked against independently calculated expectations by the test suite
(`tests/integration/test_sample_traceability.py`: hand counts and a second implementation that
reads the TOML and XML with the standard library only); step 7 shows the dashboard serves the same
values.

## Findings and fixes

1. **README activation line was wrong for Git Bash.** It said `.venv/Scripts/activate`, which in
   bash runs in a subshell and activates nothing. Fixed: the README now gives the exact command per
   shell (cmd, PowerShell, Git Bash, Linux/macOS).
2. **Windows path length.** In a deep folder (about 140 characters) `pip install -e ".[dev,e2e]"`
   failed with `No such file or directory`: the Playwright package contains files whose full path
   exceeds Windows' 260-character limit. The basic install and the demo were not affected. Fixed in
   the README: clone into a short folder or enable long paths.
3. **Windows was only checked by hand.** Fixed: CI now runs the tests and the demonstration on
   Windows (now pinned to `windows-2025`, see [ci.md](ci.md)) as well as Ubuntu.

Not a problem, noted while testing: when the output of `qi` is piped into a program that exits
early (for example a `findstr` with a wrong argument), Python reports `OSError: [Errno 22]` on
Windows (a closed pipe). The command's result is not affected when output goes to the console or a
file.

## Automated, on every push

| CI job | What it reproduces |
|---|---|
| Demonstration from a clean checkout (ubuntu-26.04, windows-2025) | fresh checkout, `pip install -e .`, `python tools/demo.py`: all eleven steps and their exit codes |
| Tests (Python 3.12, 3.13 on Ubuntu 26.04; 3.13 on Windows and on the latest Ubuntu image) | the full unit and integration suite with coverage |
| Dashboard in Chromium | the browser tests |
| Quality gates (sample data) | gate passed, failed, failed on a real attempt, incomplete |
| Self gate | the plan's acceptance criteria on this repository's own results |
