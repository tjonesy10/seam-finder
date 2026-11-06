Status: DRAFT (2026-11-06). Q1–Q2 answered; other open questions pending.

# F003: Historical DraftKings NFL Classic weekly salaries and points (2015–2021)

Related: [constitution](../../CONSTITUTION.md), [architecture](../../architecture.md), [data dictionary](../../data-dictionary.md), [glossary](../../GLOSSARY.md), [ADR 0003](../../adr/0003-rotoguru-dk-classic-salaries.md).

## Problem / job to be done

Load DraftKings NFL Classic regular-season weekly salaries and actual fantasy points for seasons 2015–2021 into Neon, keyed so later DFS backtests can join them to nflverse players, teams, and games. Source is RotoGuru's public SCSV endpoint. This unlocks historical lineup backtests. Current-slate `DKSalaries.csv` is F004; the optimizer is later.

## Requirements

- **R1** Load Classic REG-week DraftKings salary and points for seasons 2015–2021 from RotoGuru SCSV into Postgres.
- **R2** Map skill players to `gsis_id` and defense/special teams (DST) to `team_abbr`, keeping raw RotoGuru fields for provenance.
- **R3** Loads are idempotent per (season, week): upsert on the natural key, then delete that week's rows missing from the source batch.
- **R4** A failed week leaves previous data for that week in place, records failure, and fails the run.
- **R5** Every load is recorded in `load_runs` (dataset name below).
- **R6** Raw file provenance is stored (source URL, fetch time, content hash or byte length).
- **R7** Never scrape draftkings.com. Prefer a thin in-repo parser; do not pin `nfldfs`.
- **R8** No secrets in the repo or workflow logs.
- **R9** RotoGuru historical Classic DK salaries/points (2015–2021 REG) may be stored in Neon and exposed on the public site. Attribution (exact): "Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). Not affiliated with DraftKings."

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
- Target: seasons **2015–2021**, REG weeks only. [NEEDS CLARIFICATION: For each season, which weeks exist in RotoGuru (especially 2021's 18-week REG)? Default if unanswered: load every week 1–18 that returns a non-empty SCSV body with the header row; skip missing weeks with `rows_skipped` / notes, do not fail.]

### Schema

New table `dk_classic_salaries` (details in [data-dictionary.md](../../data-dictionary.md)):

| Column | Notes |
|---|---|
| season, week | REG week; PK part |
| rotoguru_gid | RotoGuru GID; PK part |
| name_raw, pos_raw, team_raw, opponent_raw, home_away | as published |
| dk_points, dk_salary | numeric; salary may be 0 in source |
| gsis_id | nullable FK → players; set for non-Def when mapped |
| team_abbr | mapped team; FK → teams when mapped; required for Def |
| opponent_abbr | mapped opponent when mapped |
| game_id | nullable FK → games when a unique REG game for (season, week, team) exists |
| source_url, source_fetched_at, source_sha256 | provenance |
| loaded_at | loader timestamp |

Natural key / PK: `(season, week, rotoguru_gid)`.

Dataset name in `load_runs`: `dk_classic_salaries` (one row per season+week).

### Mapping rules

**Teams.** Maintain an explicit in-repo map from RotoGuru lowercase codes (`nwe`, `gnb`, `jac`, `sdg`, `stl`, `oak`, …) to nflverse `team_abbr` used in F001 for that season (including historical STL, SD, OAK). [NEEDS CLARIFICATION: Confirm an explicit map table/module is the approved approach (vs free-text only). Default if unanswered: yes, explicit map; unmapped team codes fail that week.]

**Skill players (Pos ≠ Def).** Match to `players` / `player_week_stats` using normalized name (`Last, First` → display form), team, position, season, and week. Prefer a row that already played that team-week in `player_week_stats`. [NEEDS CLARIFICATION: On ambiguous or zero matches: (a) leave `gsis_id` null and keep the row, (b) skip the row, or (c) fail the week? Default if unanswered: (a) keep with null `gsis_id`, count in `notes`, and require a match-rate AT.]

**DST (Pos = Def).** Set `gsis_id` null; set `team_abbr` from the team map. Name is kept as published.

**Do not** invent stub players for RotoGuru-only names.

### Loader (CLI)

Input: `python -m loader.dk_classic --seasons 2015-2021 [--weeks 1-18] [--trigger local|manual|schedule]`.

Behavior:
- Thin in-repo HTTP fetch + SCSV parse (stdlib / httpx + existing stack). **Not** `nfldfs`. **Not** draftkings.com.
- Per (season, week), one transaction: fetch, validate header/columns, map, upsert on PK, delete that week's rows whose GID was not in the batch; write `load_runs`.
- Downloads retry 3 times. Idempotent re-run.
- Order relative to F001: requires `teams` (and preferably `players` / `games` / `player_week_stats`) already loaded for those seasons.
- [NEEDS CLARIFICATION: Refresh cadence — one-shot / manual backfill only, or also a schedule? Default if unanswered: `workflow_dispatch` only (no cron); historical source is static.]

### HTTP API and pages

- F003 is **data-load only** (table, migration, loader, workflow, tests).
- No read API endpoints and no browse page in this pass.
- API/pages are a later follow-up if Cosmo wants them before F004.

### Attribution and license

Public site and API attribution for this dataset (exact, Cosmo 2026-11-06):
"Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). Not affiliated with DraftKings."

Keep the existing nflverse footer line as well. Do not claim affiliation with DraftKings or RotoGuru.

### Security

Same secrets rule as F001. No DraftKings credentials. Public HTTP fetch only.

## Acceptance tests

Fixtures: committed SCSV snippets (at least 2015 week 1 excerpt including Def and a known skill player).

- **AT1 (R1, R6)** Fetch parse. Given the 2015 week 1 fixture, when parsed, then columns match the header, Brady (`GID 1131`) has `dk_points=27.62` and `dk_salary=7700`, and Carolina Defense (`GID 7005`) has `pos_raw=Def`, `dk_points=21`, `dk_salary=3100`.
- **AT2 (R2)** DST maps to team. Carolina Defense → `team_abbr=CAR`, `gsis_id` null.
- **AT3 (R2)** Skill player maps to gsis_id. Tom Brady 2015 week 1 maps to the same `gsis_id` as in `players` / `player_week_stats` for NE that week.
- **AT4 (R3)** Idempotent week load. Loading the fixture twice yields identical table contents (except `loaded_at` / fetch timestamps) and second run `rows_deleted=0`.
- **AT5 (R3)** Removed source row deleted. Re-load with one GID removed → that row gone and `rows_deleted=1`.
- **AT6 (R4)** Failed week keeps old data. Corrupt/missing header → tables unchanged for that week, `load_runs.status=failed`, exit 1.
- **AT7 (R5)** load_runs recorded for dataset `dk_classic_salaries` with season, week, trigger, source_url, counts.
- **AT8 (R2)** Match coverage. After loading seasons available in CI fixtures (or a recorded sample), [NEEDS CLARIFICATION: minimum skill-player match rate — propose ≥98% of non-Def rows with salary>0]. Unmapped rows follow the policy from R2 clarification.
- **AT9 (R7)** No draftkings.com and no `nfldfs` dependency in pyproject or imports.
- **AT10 (R8)** gitleaks clean; no passworded DB URLs; workflow does not print secrets.
- **AT11 (R1)** Season span. A manual or CI backfill for 2015–2021 only requests REG weeks; no POST weeks are written.

## Non-goals

- Current-slate DraftKings `DKSalaries.csv` (F004).
- Showdown / single-game contests.
- FanDuel, Yahoo, or other DFS sites.
- Optimizer / lineup generation.
- Scraping draftkings.com.
- Playoff weeks.
- Pinning `nfldfs`.
- Public API and HTML pages for this table.

## Allowed dependencies

Existing F001 stack plus `httpx` (already present). Stdlib CSV/semicolon parse. Not allowed without asking: `nfldfs`, pandas, ORM, any DraftKings API client, paid data.

## Open questions

1. ~~License / constitution (R9).~~ Answered 2026-11-06.
2. ~~Deliverable scope.~~ Answered 2026-11-06: data-load only (no API/pages this pass).
3. **Unmapped skill players.** Keep with null `gsis_id`, skip, or fail the week? Minimum match-rate for AT8?
4. **Team map.** Confirm explicit RotoGuru→nflverse team_abbr map (recommended default: yes).
5. **Weeks.** Confirm per-season week discovery (recommended default: load weeks that return SCSV).
6. **Refresh.** Manual/`workflow_dispatch` only vs also scheduled (recommended default: manual only)?
7. **Zero salaries.** Load rows with `dk_salary=0` as-is (recommended default: yes)?

## Decisions (from Cosmo via Groko, 2026-11-06)

- Feature approved: historical DK Classic weekly salaries and points 2015–2021 via RotoGuru → Neon.
- Prefer thin in-repo parser; do not pin `nfldfs`.
- Never scrape draftkings.com.
- Not F004 (current slate) and not the optimizer.
- Phase order remains 0→1→4→2→3→5→6→7; README methodologies stay aspirational.
- **Q1:** Yes — store in Neon and expose on the public site. Attribution exact: "Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). Not affiliated with DraftKings."
- **Q2:** Data-load only — migration, tables, RotoGuru loader, workflow, tests. No read API or browse page in this pass (follow-up later).

## ADRs

- [ADR 0001: Stack and hosting](../../adr/0001-stack-and-hosting.md)
- [ADR 0002: nflverse load and refresh](../../adr/0002-nflverse-load-and-refresh.md)
- [ADR 0003: RotoGuru DK Classic salaries](../../adr/0003-rotoguru-dk-classic-salaries.md) (Proposed → Accepted once constitution amendment merges)
