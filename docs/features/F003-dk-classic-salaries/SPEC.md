Status: READY (2026-11-06). All clarifications answered. Analyze pass recorded in HANDOFF.md.

# F003: Historical DraftKings NFL Classic weekly salaries and points (2015–2021)

Related: [constitution](../../CONSTITUTION.md), [architecture](../../architecture.md), [data dictionary](../../data-dictionary.md), [glossary](../../GLOSSARY.md), [ADR 0003](../../adr/0003-rotoguru-dk-classic-salaries.md).

## Problem / job to be done

Load DraftKings NFL Classic regular-season weekly salaries and actual fantasy points for seasons 2015–2021 into Neon, keyed so later DFS backtests can join them to nflverse players, teams, and games. Source is RotoGuru's public SCSV endpoint. This unlocks historical lineup backtests. Current-slate `DKSalaries.csv` is F004; the optimizer is later.

## Requirements

- **R1** Load Classic REG-week DraftKings salary and points for seasons 2015–2021 from RotoGuru SCSV into Postgres, including rows with `dk_salary=0`.
- **R2** Map skill players to `gsis_id` and defense/special teams (DST) to `team_abbr`, keeping raw RotoGuru fields for provenance. Unmapped skill rows stay with null `gsis_id`; unmapped team codes fail that week.
- **R3** Loads are idempotent per (season, week): upsert on the natural key, then delete that week's rows missing from the source batch.
- **R4** A failed week leaves previous data for that week in place, records failure, and fails the run.
- **R5** Every load is recorded in `load_runs` (dataset name below). Unmapped skill counts go in `notes`.
- **R6** Raw file provenance is stored (source URL, fetch time, content hash or byte length).
- **R7** Never scrape draftkings.com. Prefer a thin in-repo parser; do not pin `nfldfs`.
- **R8** No secrets in the repo or workflow logs.
- **R9** RotoGuru historical Classic DK salaries/points (2015–2021 REG) may be stored in Neon and exposed on the public site. Attribution (exact): "Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). Not affiliated with DraftKings." This pass stores the data and commits that string as a named constant for later pages; it does not add API/pages.
- **R10** Refresh is `workflow_dispatch` / manual (and local CLI) only — no cron for this dataset.

## User stories

1. As Cosmo, I want 2015–2021 Classic weekly DK salaries and points in the database, so that DFS backtests have a salary history.
2. As an engineer, I want each row joined to `gsis_id` or `team_abbr`, so that backtests reuse F001 keys.
3. As Cosmo, I want a re-runnable loader with `load_runs`, so that I can backfill or repair without silent drift.

## Observable behavior

### Source (verified 2026-11-06)

- URL: `http://rotoguru1.com/cgi-bin/fyday.pl?week={W}&year={Y}&game=dk&scsv=1` (HTTPS may fail; HTTP works).
- Header: `Week;Year;GID;Name;Pos;Team;h/a;Oppt;DK points;DK salary`
- Semicolon-delimited. Names are `Last, First`. Positions include `QB`, `RB`, `WR`, `TE`, `Def`.
- DST example (2015 week 1): `1;2015;7005;Carolina Defense;Def;car;a;jac;21;3100`
- Page note: salaries reflect all-week (Thurs–Mon) Classic slates; playoff weeks are not produced; Showdown is out of scope.
- Target: seasons **2015–2021**, REG weeks only. Load every week 1–18 that returns a non-empty SCSV body with the header row; skip missing weeks with `rows_skipped` / notes; do not fail the run solely because a week is absent.

### Schema

New table `dk_classic_salaries` (details in [data-dictionary.md](../../data-dictionary.md)):

| Column | Notes |
|---|---|
| season, week | REG week; PK part |
| rotoguru_gid | RotoGuru GID; PK part |
| name_raw, pos_raw, team_raw, opponent_raw, home_away | as published |
| dk_points, dk_salary | numeric; salary may be 0 in source — load as-is |
| gsis_id | nullable FK → players; set for non-Def when mapped |
| team_abbr | mapped team; FK → teams when mapped; required for Def |
| opponent_abbr | mapped opponent when mapped |
| game_id | nullable FK → games when a unique REG game for (season, week, team) exists |
| source_url, source_fetched_at, source_sha256 | provenance |
| loaded_at | loader timestamp |

Natural key / PK: `(season, week, rotoguru_gid)`.

Dataset name in `load_runs`: `dk_classic_salaries` (one row per season+week).

### Mapping rules

**Teams.** Maintain an explicit in-repo map from RotoGuru lowercase codes (`nwe`, `gnb`, `jac`, `sdg`, `stl`, `oak`, …) to nflverse `team_abbr` used in F001 for that season (including historical STL, SD, OAK). Special case (built): `oak` → `OAK` for seasons ≤2019 and `LV` for seasons ≥2020. Unmapped team codes fail that week (previous data kept; `load_runs.status=failed`). Opponent code `-` is currently treated as unmapped and fails the week — Cosmo follow-up whether to treat as bye/unknown (null `opponent_abbr`) instead.

**Skill players (Pos ≠ Def).** Match to `players` / `player_week_stats` using normalized name (`Last, First` → display form), team, position, season, and week. Prefer a row that already played that team-week in `player_week_stats`. On ambiguous or zero matches: leave `gsis_id` null, keep the row, and count unmapped in `load_runs.notes`. Do not invent stub players.

**DST (Pos = Def).** Set `gsis_id` null; set `team_abbr` from the team map only. Name is kept as published.

### Loader (CLI)

Input: `python -m loader.dk_classic --seasons 2015-2021 [--weeks 1-18] [--trigger local|manual]`.

Behavior:
- Thin in-repo HTTP fetch + SCSV parse (stdlib / httpx + existing stack). **Not** `nfldfs`. **Not** draftkings.com.
- Per (season, week), one transaction: fetch, validate header/columns, map, upsert on PK, delete that week's rows whose GID was not in the batch; write `load_runs`.
- Downloads retry 3 times. Idempotent re-run.
- Order relative to F001: requires `teams` (and preferably `players` / `games` / `player_week_stats`) already loaded for those seasons.
- GitHub Actions: `workflow_dispatch` only (no cron). Historical source is static.

### HTTP API and pages

- F003 is **data-load only** (table, migration, loader, workflow, tests).
- No read API endpoints and no browse page in this pass.
- API/pages are a later follow-up if Cosmo wants them before F004.

### Attribution and license

Commit the exact attribution string as a named constant for later public pages (this pass has no pages):
"Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). Not affiliated with DraftKings."

Keep the existing nflverse footer line as well when pages exist. Do not claim affiliation with DraftKings or RotoGuru.

### Security

Same secrets rule as F001. No DraftKings credentials. Public HTTP fetch only.

## Acceptance tests

Fixtures: committed SCSV snippets (at least 2015 week 1 excerpt including Def, a known skill player, and if available a `dk_salary=0` row).

- **AT1 (R1, R6)** Fetch parse. Given the 2015 week 1 fixture, when parsed, then columns match the header, Brady (`GID 1131`) has `dk_points=27.62` and `dk_salary=7700`, and Carolina Defense (`GID 7005`) has `pos_raw=Def`, `dk_points=21`, `dk_salary=3100`.
- **AT2 (R2)** DST maps to team. Carolina Defense → `team_abbr=CAR`, `gsis_id` null.
- **AT3 (R2)** Skill player maps to gsis_id. Tom Brady 2015 week 1 maps to the same `gsis_id` as in `players` / `player_week_stats` for NE that week.
- **AT4 (R3)** Idempotent week load. Loading the fixture twice yields identical table contents (except `loaded_at` / fetch timestamps) and second run `rows_deleted=0`.
- **AT5 (R3)** Removed source row deleted. Re-load with one GID removed → that row gone and `rows_deleted=1`.
- **AT6 (R4)** Failed week keeps old data. Corrupt/missing header → tables unchanged for that week, `load_runs.status=failed`, exit 1.
- **AT7 (R5)** load_runs recorded for dataset `dk_classic_salaries` with season, week, trigger, source_url, counts; unmapped skill count appears in `notes` when any.
- **AT8 (R2)** Match coverage. After loading seasons available in CI fixtures (or a recorded sample), ≥98% of non-Def rows with `dk_salary>0` have a non-null `gsis_id`. Unmapped skill rows remain with null `gsis_id`.
- **AT9 (R7)** No draftkings.com and no `nfldfs` dependency in pyproject or imports.
- **AT10 (R8)** gitleaks clean; no passworded DB URLs; workflow does not print secrets.
- **AT11 (R1)** Season span / week discovery. A manual or CI backfill for 2015–2021 only requests REG weeks 1–18; missing SCSV weeks are skipped (noted), not failed; no POST weeks are written.
- **AT12 (R1)** Zero salaries. A fixture row with `dk_salary=0` is loaded with salary 0 (not dropped).
- **AT13 (R9)** Attribution constant. The exact Cosmo attribution string is defined in one committed source constant (for later pages).
- **AT14 (R2, R4)** Unmapped team code. A fixture week with an unknown `team_raw` fails that week, leaves prior rows for that week unchanged, and records `load_runs.status=failed`.
- **AT15 (R10)** No cron. The F003 GitHub Actions workflow has `workflow_dispatch` only (no `schedule`).

## Non-goals

- Current-slate DraftKings `DKSalaries.csv` (F004).
- Showdown / single-game contests.
- FanDuel, Yahoo, or other DFS sites.
- Optimizer / lineup generation.
- Scraping draftkings.com.
- Playoff weeks.
- Pinning `nfldfs`.
- Public API and HTML pages for this table (follow-up).
- Scheduled / cron refresh of this historical dataset.

## Allowed dependencies

Existing F001 stack plus `httpx` (already present). Stdlib CSV/semicolon parse. Not allowed without asking: `nfldfs`, pandas, ORM, any DraftKings API client, paid data.

## Open questions

None. Q1–Q7 answered 2026-11-06.

## Decisions (from Cosmo via Groko, 2026-11-06)

- Feature approved: historical DK Classic weekly salaries and points 2015–2021 via RotoGuru → Neon.
- Prefer thin in-repo parser; do not pin `nfldfs`.
- Never scrape draftkings.com.
- Not F004 (current slate) and not the optimizer.
- Phase order remains 0→1→4→2→3→5→6→7; README methodologies stay aspirational.
- **Q1:** Yes — store in Neon and expose on the public site. Attribution exact: "Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). Not affiliated with DraftKings."
- **Q2:** Data-load only — migration, tables, RotoGuru loader, workflow, tests. No read API or browse page in this pass (follow-up later).
- **Q3:** Unmapped skill (Pos ≠ Def): keep row with null `gsis_id`; count in `load_runs.notes`; AT8 ≥98% matched among non-Def rows with `salary > 0`. DST keys by team only.
- **Q4:** Explicit in-repo RotoGuru → nflverse `team_abbr` map; unmapped team codes fail that week.
- **Q5:** Load any week 1–18 that returns SCSV within 2015–2021 REG; skip missing weeks without failing the run.
- **Q6:** Refresh = manual / `workflow_dispatch` only (no cron).
- **Q7:** Keep rows with `dk_salary=0`.

## ADRs

- [ADR 0001: Stack and hosting](../../adr/0001-stack-and-hosting.md)
- [ADR 0002: nflverse load and refresh](../../adr/0002-nflverse-load-and-refresh.md)
- [ADR 0003: RotoGuru DK Classic salaries](../../adr/0003-rotoguru-dk-classic-salaries.md) (Proposed → Accepted once constitution amendment merges on main)
