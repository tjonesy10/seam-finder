# Playwright setup hardening

Date: 2026-11-11. Branch `cursor/playwright-ci-retry-fd3f`. Base `1f6047647bbe896794a113c51778ae2b0cd1b3fd` (main, merge of PR #36). Workflow, install helper, and this report only. No app, API, schema, migration, Render, secret, baseline, threshold, or axe change.

`git fetch origin main` then `git merge origin/main` reported `Already up to date`. Main was already an ancestor, so there is no merge commit.

## Root cause

[Run 43040881501](https://github.com/tjonesy10/seam-finder/actions/runs/43040881501) on main merge `1f6047647bbe896794a113c51778ae2b0cd1b3fd` (PR #36) failed both attempts. Attempt 1 finished 2026-11-11T14:52:24Z. Attempt 2 finished 2026-11-11T15:05:33Z. In both `test` and `visual`, the only failed step was `Install Playwright` (`npx playwright install --with-deps chromium`). Apt exited 100 while fetching font packages (`fonts-ipafont-gothic`, `fonts-freefont-ttf`, `fonts-tlwg-loma-otf`, `fonts-unifont`, `fonts-wqy-zenhei`, and the xfonts packages). The log lines are `Temporary failure resolving 'azure.archive.ubuntu.com'`, `archive.ubuntu.com`, and `security.ubuntu.com`. Test, frontend end-to-end, and visual comparison steps were skipped. Nothing in the repository changed between the attempts. This was a transient Ubuntu mirror/DNS outage, not an application failure.

## Approach

Option (b). Keep `test` on `ubuntu-latest` and `visual` on `ubuntu-24.04`.

The official `mcr.microsoft.com/playwright:v1.65.0-noble` image was not used. F010/F011 baselines were captured on the GitHub `ubuntu-24.04` runner (ADR 0010 and the F010 spec). That image is Ubuntu 24.04, but it is not the runner image and ships a different preinstalled font stack. A container that changes font rendering would force a baseline refresh. This change does not regenerate or edit any baseline, and it does not loosen `maxDiffPixels`, `threshold`, or axe rules.

`frontend/package-lock.json` pins `@playwright/test` at 1.65.0. Each job caches `~/.cache/ms-playwright` with key `Linux-ms-playwright-<job>-<that version>`. `.github/scripts/install-playwright-chromium.sh` writes apt `Acquire::Retries "5"` plus 30s HTTP and HTTPS timeouts, then retries `npx playwright install chromium` and `npx playwright install-deps chromium` up to 4 times with backoff (20s, 40s, 80s, capped at 120s). OS packages are installed on every run because they are not in the browser cache. After the last failure the step exits with the installer's status (apt's 100 in the incident).

### Token permissions

`actions: write` was on the first commit of this branch and is removed. `actions/cache` reads and writes cache entries with the Actions runtime token. It does not need the workflow `GITHUB_TOKEN` `actions` scope. Permissions stay `contents: read`, the same as main. No job adds a broader scope.

## Retry path

Verified locally against the `retry` function in `.github/scripts/install-playwright-chromium.sh` (sourced, so `main` did not run apt):

- A command that exits 100 once, then 0: the log shows `attempt 1/4 failed (exit 100); retrying in 1s` and `succeeded on attempt 2/4`. Exit 0.
- A command that always exits 100, with `set -e` and 2 attempts: the log shows the retry, then `failed after 2 attempts (exit 100)`. The shell exits 100.

The in-CI backoff branch is UNKNOWN until a GitHub log shows a failed attempt followed by a later success. A green run that prints `succeeded on attempt 1/4` only shows that the wrapper ran and the mirror was healthy on the first try.

## Baselines unchanged

`git diff --name-only origin/main` for this branch:

- `.github/scripts/install-playwright-chromium.sh`
- `.github/workflows/ci.yml`
- `docs/ci/playwright-setup-hardening/TEST_REPORT.md`

No path under `frontend/e2e/`, and no `*.png`, is in the diff. `frontend/playwright.config.ts` is untouched (`maxDiffPixels: 100`, `threshold: 0.2`). The visual job still runs on `ubuntu-24.04`. CI does not pass `--update-snapshots`.

## CI evidence

Head checks for the commit that adds this report are the acceptance runs. Both the `push` and `pull_request` workflows run `ci.yml`. This section is updated with those run URLs and job conclusions when they finish. Until then, the only completed CI evidence is the failed main run linked above.

Previous head `bf27d4ed0a7fa9ae9e334ea730519ece612434fa` started [push run 43046117041](https://github.com/tjonesy10/seam-finder/actions/runs/43046117041) and [pull_request run 43046141161](https://github.com/tjonesy10/seam-finder/actions/runs/43046141161). When this report was written, both were still inside `Install Playwright` (`test` and `visual`), so they are not a pass or fail result here. That head still granted `actions: write`; this commit removes it.
