# F014 evidence snapshot

Research base: `origin/main` `e84fa87df1367b9f69cdbe61158f336aca391c11`, fetched 2026-11-11. PR #42 was open, non-draft, at `2a89f83fb3cc15eeb6c7becc768190c576199ebe`; its tree reserves ADR 0012 and extends F005 to R14/AT31. Main reserves ADRs 0001–0011 and features through F013. Thus this proposal uses ADR 0013 and F014. PR #42 is a contract dependency, not copied into this patch or declared merged.

## Workflow inventory at the research base

| Workflow | Triggers; cron and timezone | Token permissions | Concurrency | Source |
|---|---|---|---|---|
| ci.yml | pull_request; push on main and **; no schedule or dispatch | contents:read | None declared | `.github/workflows/ci.yml:1–13` (entire file has no concurrency key) |
| refresh.yml | daily `0 11 * * *`; no timezone key, therefore UTC; workflow_dispatch with optional seasons | contents:read | None declared | `.github/workflows/refresh.yml:3–52` |
| dk-classic-salaries.yml | workflow_dispatch only, seasons/weeks | contents:read | None declared | `.github/workflows/dk-classic-salaries.yml:3–51` |
| dk-classic-slate.yml | Tuesday `0 15 * * 2`; no timezone key, therefore UTC; workflow_dispatch with season/week/staged-file inputs | contents:read, actions:read (staged artifact access) | None declared | `.github/workflows/dk-classic-slate.yml:13–101` |
| dk-lobby-capture.yml | Wednesday `7 10 * * 3`, timezone America/New_York; workflow_dispatch with season/week/selector | contents:read | group dk-lobby-capture, cancel-in-progress:false | `.github/workflows/dk-lobby-capture.yml:7–44` |

The capture's exact-true gate precedes migration (`dk-lobby-capture.yml:58–68`); its Capture step calls only `loader.dk_lobby`, not the normal refresh (`:70–110`). Normal refresh migrates, then runs `python -m loader` (`refresh.yml:32–52`). Loader order is teams, players, games, stats (`loader/run.py:676–718`), with dataset/season audit and rollback behavior in `:276–305`. The games transaction stores the raw schedule and attempts its receipt (`:516–596`). Optional receipt production can return false while the public load succeeds (`loader/schedule_proof.py:766–808,835–858`). A green refresh alone is therefore not enough.

Capture acquires the private session lock, reads proof, creates its attempt, and only then attempts HTTP (`loader/dk_lobby.py:1397–1502`). Evidence is checked in a consistent read (`loader/schedule_proof.py:566–578`); receipt assessment checks publisher version, raw projection, successful matching games load, retrieval age and current whole-season PG equality (`:389–459`). It picks the latest eligible matching receipt, not a designated just-completed refresh (`:462–479`). Retrieval age is 24 hours with at most five minutes future skew (`:23–24,245–252`). The producer currently passes its post-fetch load timestamp as retrieved_at (`loader/run.py:520–522,550–575`); F014 must preserve the real upstream-retrieval meaning, not use a copied-file mtime or completion stamp to renew old bytes.

If today's refresh arrives late, yesterday's receipt can still be under 24 hours old and pass, or can have expired and fail. Missing/mismatched proof fails schedule_evidence_missing before DK; it does not establish that the immediately preceding scheduled refresh finished. Schedule data, not stats, determines coverage, REG season/week and exact Sunday game membership/kickoffs. This is not a dependency on a materialized-view refresh; F008 is a separate private SQL view (ADR 0006:13–26). F007's bounded archive-clock tolerance (ADR 0009:24) does not relax F005 exactness.

Existing private lock is CAPTURE_LOCK (`loader/salary_private.py:124–131`); the receipt producer takes a transaction lock on that same key (`loader/schedule_proof.py:728–729`). An outer lock on that key using a different connection would deadlock its child producer. The proposed coordination lock is separate, acquired first by all participating entry points.

## Schedule-run creation delays

Read-only public REST query for **each** workflow: `GET https://api.github.com/repos/tjonesy10/seam-finder/actions/workflows/{filename}/runs?event=schedule&created=%3E%3D2026-11-01&per_page=100`. Queried 2026-11-11 around 12:19 EST. Counts were 5 refresh, 1 staged slate, 0 lobby, 0 historical salaries, 0 CI. Every response fit one page. All timestamps below are America/New_York (EST). Expected slots are inferred from the workflow cron in force, not a scheduled_at field (the runs API supplies none). created_at measures event/run creation, not job completion or end-to-end latency. run_started_at equalled created_at for these six records.

| Workflow / run | Expected slot EST | created_at EST | Creation delay | Conclusion |
|---|---|---|---|---|
| refresh.yml / [42264277224](https://github.com/tjonesy10/seam-finder/actions/runs/42264277224) | 2026-11-06 06:00:00 | 2026-11-06 12:43:45 | 6h 43m 45s | success |
| refresh.yml / [42392477036](https://github.com/tjonesy10/seam-finder/actions/runs/42392477036) | 2026-11-07 06:00:00 | 2026-11-07 11:40:31 | 5h 40m 31s | success |
| refresh.yml / [42501782958](https://github.com/tjonesy10/seam-finder/actions/runs/42501782958) | 2026-11-08 06:00:00 | 2026-11-08 11:48:48 | 5h 48m 48s | success |
| refresh.yml / [42699964899](https://github.com/tjonesy10/seam-finder/actions/runs/42699964899) | 2026-11-09 06:00:00 | 2026-11-09 16:10:27 | 10h 10m 27s | success |
| refresh.yml / [42874361204](https://github.com/tjonesy10/seam-finder/actions/runs/42874361204) | 2026-11-10 06:00:00 | 2026-11-10 13:21:26 | 7h 21m 26s | success |
| dk-classic-slate.yml / [42902548227](https://github.com/tjonesy10/seam-finder/actions/runs/42902548227) | 2026-11-10 10:00:00 | 2026-11-10 16:11:14 | 6h 11m 14s | failure |

No schedule run for refresh on November 11 or lobby on November 11 was returned at the observation time; absence cannot distinguish delayed from dropped. The lobby minute-7 change was authored at 10:55 EST on November 11 (commit `5b2ee03`) and reached main via PR #41 at 12:13 EST, after that day's intended minute-0 slot; this is not evidence about a completed 10:07 schedule run. There are no November 1–5 refresh records in the query, and refresh.yml first appeared November 5 (commit `9cf5d01`). Staged-slate workflow appeared November 6 (`0acdd17`); November 10 was its only due Tuesday in the remaining window. CI and historical salaries have no cron, so zero schedule records is expected. Do not fabricate delays for absent events.

## Manual-dispatch 403

Both relevant workflows already declare workflow_dispatch (`refresh.yml:6`, `dk-lobby-capture.yml:12`). Missing trigger is not the leading explanation. The dispatching credential needs repository access and Actions:write for fine-grained/app tokens; classic/OAuth requirements are documented as repo scope. Repository policy can further restrict the caller. The target workflow's contents:read controls its own runtime GITHUB_TOKEN, not an outside agent's authorization; changing target permissions cannot repair an external caller's token. Insufficient caller Actions permission is plausible, not proven. No credential or token was inspected and no dispatch was attempted.

F014 does not need a dispatch, so this 403 is not on the build path. Fixing agent-initiated `gh workflow run` is a non-goal. Likely cause: the caller's credential lacks repository Actions write permission (unproven).

## Public documentation checked 2026-11-11

- [Workflow REST dispatch requirements](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event).
- [Fine-grained token permission reference](https://docs.github.com/en/rest/authentication/permissions-required-for-fine-grained-personal-access-tokens#repository-permissions-for-actions).
- [Workflow syntax: schedule, timezone and permissions](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).
- [Schedule delay/drop and manual dispatch](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

No public API response contains a guaranteed scheduler deadline. Moving a cron earlier does not impose one. This investigation did not call DK, read production, change repository variables or authenticate a new identity.
