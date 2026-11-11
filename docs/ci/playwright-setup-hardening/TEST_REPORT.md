# Playwright setup hardening

Date: 2026-11-11. Branch `cursor/playwright-ci-retry-fd3f`. Base `1f6047647bbe896794a113c51778ae2b0cd1b3fd` (main, merge of PR #36). Workflow, install helper, and this report only. No app, API, schema, migration, Render, secret, baseline, threshold, or axe change.

`git fetch origin main` then `git merge origin/main` reported `Already up to date`. Main was already an ancestor, so there is no merge commit.

## Root cause

[Run 43040881501](https://github.com/tjonesy10/seam-finder/actions/runs/43040881501) on main merge `1f6047647bbe896794a113c51778ae2b0cd1b3fd` (PR #36) failed both attempts. Attempt 1 finished 2026-11-11T14:52:24Z. Attempt 2 finished 2026-11-11T15:05:33Z. In both `test` and `visual`, the only failed step was `Install Playwright` (`npx playwright install --with-deps chromium`). Apt exited 100 while fetching font packages (`fonts-ipafont-gothic`, `fonts-freefont-ttf`, `fonts-tlwg-loma-otf`, `fonts-unifont`, `fonts-wqy-zenhei`, and the xfonts packages). The log lines are `Temporary failure resolving 'azure.archive.ubuntu.com'`, `archive.ubuntu.com`, and `security.ubuntu.com`. Test, frontend end-to-end, and visual comparison steps were skipped. Nothing in the repository changed between the attempts. This was a transient Ubuntu mirror/DNS outage, not an application failure.

## Approach

Option (b). Keep `test` on `ubuntu-latest` and `visual` on `ubuntu-24.04`.

The official `mcr.microsoft.com/playwright:v1.65.0-noble` image was not used. F010/F011 baselines were captured on the GitHub `ubuntu-24.04` runner (ADR 0010 and the F010 spec). That image is Ubuntu 24.04, but it is not the runner image and ships a different preinstalled font stack. A container that changes font rendering would force a baseline refresh. This change does not regenerate or edit any baseline, and it does not loosen `maxDiffPixels`, `threshold`, or axe rules.

`frontend/package-lock.json` pins `@playwright/test` at 1.65.0. Each job caches `~/.cache/ms-playwright` with key `Linux-ms-playwright-<job>-<that version>`. `.github/scripts/install-playwright-chromium.sh` writes apt `Acquire::Retries "5"` plus 30s HTTP and HTTPS timeouts, then retries browser install and OS-deps install up to 4 times with backoff (20s, 40s, 80s, capped at 120s). OS packages are installed on every run because they are not in the browser cache.

Four apt attempts were not enough on their own. Each dead attempt spends about ten minutes failing over `azure.archive.ubuntu.com`, `archive.ubuntu.com`, and `security.ubuntu.com`. On head `bf27d4e` that covered 15:14Z–15:56Z and DNS was still down, so both jobs exited after attempt 4. The helper now probes those three names with a 5s timeout. When all three resolve, the runner mirror list is left as GitHub wrote it. When any of them do not resolve, apt is pointed only at the names that do. When none do, it is pointed at the fallbacks that resolve: `mirrors.kernel.org`, `mirrors.edge.kernel.org`, `mirror.csclub.uwaterloo.ca`, and `mirrors.ocf.berkeley.edu`. Those URLs publish the same Ubuntu archive pool (the noble and resolute `fonts-ipafont-gothic` debs from the failed log return HTTP 200 there). If no name resolves, apt is skipped for that attempt and the backoff runs again. A healthy runner never changes mirrors, so the visual job still installs the same packages from the same archives.

### Token permissions

`actions: write` was on the first commit of this branch and is removed. `actions/cache` reads and writes cache entries with the Actions runtime token. It does not need the workflow `GITHUB_TOKEN` `actions` scope. Permissions stay `contents: read`, the same as main. No job adds a broader scope.

## Retry path

Verified locally against the `retry` function in `.github/scripts/install-playwright-chromium.sh` (sourced, so `main` did not run apt):

- A command that exits 100 once, then 0: the log shows `attempt 1/4 failed (exit 100); retrying in 1s` and `succeeded on attempt 2/4`. Exit 0.
- A command that always exits 100, with `set -e` and 2 attempts: the log shows the retry, then `failed after 2 attempts (exit 100)`. The shell exits 100.

In CI, the backoff path ran on [push run 43046117041](https://github.com/tjonesy10/seam-finder/actions/runs/43046117041) (head `bf27d4ed0a7fa9ae9e334ea730519ece612434fa`). In both `test` and `visual`, `npx playwright install chromium` logged `succeeded on attempt 1/4`. `npx playwright install-deps chromium` then logged `attempt 1/4 failed (exit 1); retrying in 20s`, `attempt 2/4 failed (exit 1); retrying in 40s`, and `attempt 3/4 failed (exit 1); retrying in 80s`, and the step ended with `failed after 4 attempts (exit 1)`. Each attempt was apt exit 100, `Temporary failure resolving` the three Ubuntu archive names while fetching the same font packages as run 43040881501. [Pull request run 43046141161](https://github.com/tjonesy10/seam-finder/actions/runs/43046141161) on that head also failed both jobs. That is a real failed-then-retry path. It is not a later success: the outage outlasted the four attempts (about 15:14Z–15:56Z).

## Baselines unchanged

`git diff --name-only origin/main` for this branch:

- `.github/scripts/install-playwright-chromium.sh`
- `.github/workflows/ci.yml`
- `docs/ci/playwright-setup-hardening/TEST_REPORT.md`

No path under `frontend/e2e/`, and no `*.png`, is in the diff. `frontend/playwright.config.ts` is untouched (`maxDiffPixels: 100`, `threshold: 0.2`). The visual job still runs on `ubuntu-24.04`. CI does not pass `--update-snapshots`.

## CI evidence

| Run | Event | Head | `test` | `visual` |
|---|---|---|---|---|
| [43040881501](https://github.com/tjonesy10/seam-finder/actions/runs/43040881501) | push to main, attempts 1 and 2 | `1f6047647bbe896794a113c51778ae2b0cd1b3fd` | failure (apt exit 100, no tests) | failure (apt exit 100, no comparisons) |
| [43046117041](https://github.com/tjonesy10/seam-finder/actions/runs/43046117041) | push | `bf27d4ed0a7fa9ae9e334ea730519ece612434fa` | failure after 4 dep attempts | failure after 4 dep attempts |
| [43046141161](https://github.com/tjonesy10/seam-finder/actions/runs/43046141161) | pull_request | `bf27d4ed0a7fa9ae9e334ea730519ece612434fa` | failure | failure |
| [43049385207](https://github.com/tjonesy10/seam-finder/actions/runs/43049385207) | push | `264f342faa5fb57b37c484fd8aaadce2d08f3a9c` | failure | failure |
| [43049403544](https://github.com/tjonesy10/seam-finder/actions/runs/43049403544) | pull_request | `264f342faa5fb57b37c484fd8aaadce2d08f3a9c` | failure | failure |

`264f342` removed `actions: write` and added the first copy of this report. It did not change the install script. Both of its workflows were still on the public Actions page as running at 16:15:29Z and failed at 16:16:45Z, about 43 minutes after Install Playwright started (15:33Z). That matches the four-attempt apt exhaustion on `bf27d4e` (15:13Z–15:56Z).

Head `1c7d72bc9542bec7167f9ad3c953f753dc02cf6d` adds the mirror fallback and merges main `a3cbd5d`. Both workflows passed:

| Run | Event | `test` | `visual` |
|---|---|---|---|
| [43057072259](https://github.com/tjonesy10/seam-finder/actions/runs/43057072259) | push | success, including Test and Frontend end-to-end | success, including Visual and accessibility comparisons (run twice). Upload synthetic visual diffs skipped |
| [43057081277](https://github.com/tjonesy10/seam-finder/actions/runs/43057081277) | pull_request | success | success |

On the push run, both jobs logged `mirror dns miss` for `azure.archive.ubuntu.com`, `archive.ubuntu.com`, and `security.ubuntu.com`, then `fallback dns ok` for `mirrors.kernel.org`, `mirrors.edge.kernel.org`, `mirror.csclub.uwaterloo.ca`, and `mirrors.ocf.berkeley.edu`, wrote `/etc/apt/apt-mirrors.txt`, and `succeeded on attempt 1/4: install_chromium_deps`. Browser install was `succeeded on attempt 1/4`. Visual comparisons passed on that fallback mirror set, so the committed baselines stayed valid without an update. `Post Cache Playwright browsers` succeeded and saved `Linux-ms-playwright-visual-1.65.0` with workflow permissions still `contents: read` only. Recording these results does not change the workflow.
