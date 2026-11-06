Status: DRAFT (2026-11-06). Q1–Q2 answered; other open questions pending.

# F004: Current-slate DraftKings NFL Classic salaries (`DKSalaries.csv`)

Related: [constitution](../../CONSTITUTION.md), [architecture](../../architecture.md), [data dictionary](../../data-dictionary.md), [glossary](../../GLOSSARY.md), [ADR 0004](../../adr/0004-dk-current-slate-csv.md), [F003 SPEC](../F003-dk-classic-salaries/SPEC.md).

## Problem / job to be done

Load Cosmo's official DraftKings NFL Classic salary export (`DKSalaries.csv`) into Neon so a later optimizer can use today's (or a chosen week's) salaries joined to F001 players/teams. Historical Classic salaries stay in F003 (RotoGuru). Never scrape draftkings.com.

## Requirements

- **R1** Ingest a user-supplied DraftKings Classic `DKSalaries.csv` (file path / Cosmo paste or upload — path TBD) into Postgres.
- **R2** Map skill players to `gsis_id` and DST to `team_abbr`, keeping raw DK fields (including DraftKings `ID`) for provenance and lineup export later.
- **R3** Loads are idempotent per `(season, week)`: upsert on `(season, week, dk_id)`, then delete that season/week's rows missing from the batch.
- **R4** A failed load leaves previous data for that slate in place, records failure, and fails the run.
- **R5** Every load is recorded in `load_runs` (dataset name below).
- **R6** Provenance is stored (source filename or upload id, fetch/load time, content hash).
- **R7** Never scrape or download from draftkings.com. Cosmo supplies the CSV.
- **R8** No secrets in the repo or logs. Do not commit live salary CSVs with personal contest data unless Cosmo explicitly allows a redacted fixture.
- **R9** Store Cosmo's official Classic `DKSalaries.csv` in Neon for personal/optimizer use. Do **not** publish raw salary tables or CSV downloads on the public site. Any UI that mentions DraftKings must include "Not affiliated with DraftKings."

## User stories

1. As Cosmo, I want this week's Classic salaries in the database from my DK export, so that an optimizer can use live prices.
2. As an engineer, I want each row joined to `gsis_id` or `team_abbr`, so that projections and F001 stats join cleanly.
3. As Cosmo, I want re-loading a corrected CSV to replace that slate safely, so that I can fix a bad export without manual deletes.

## Observable behavior

### Source (expected shape)

Official DraftKings Classic "Export to CSV" columns (order may vary; extra columns ignored):

`Position,Name + ID,Name,ID,Roster Position,Salary,Game Info,TeamAbbrev,AvgPointsPerGame`

- `ID` is the DraftKings player/defense id (integer/string).
- `Roster Position` may list multiple slots (e.g. `QB`, `RB/FLEX`, `DST`).
- `Game Info` looks like `KC@DEN 10/12/2026 04:20PM ET` (or similar); used to derive opponent / kickoff when possible.
- NFL Classic only this feature. Showdown / single-game is out of scope.
- Slate identity: Cosmo passes `--season` and `--week` on the CLI. Natural key `(season, week, dk_id)`.

### Schema (proposed)

New table `dk_classic_slate` (name TBD in data dictionary):

| Column | Notes |
|---|---|
| season, week | REG week Cosmo passes on load; PK part |
| dk_id | DraftKings ID; PK part |
| name_raw, position_raw, roster_position_raw, team_raw, game_info_raw | as published |
| salary, avg_points_per_game | numeric |
| gsis_id | nullable FK → players |
| team_abbr | mapped; required for DST |
| opponent_abbr | from Game Info when parseable |
| game_id | nullable FK → games when unique match exists |
| source_name, source_sha256, source_loaded_at | provenance |
| loaded_at | loader timestamp |

Dataset name in `load_runs`: `dk_classic_slate`.

### Mapping rules

- Reuse F001/`gsis_id` matching approach from F003 where it fits (name, team, position); DK `TeamAbbrev` is already nfl-like (KC, DEN, …).
- DST: `Position`/`Roster Position` containing DST → `gsis_id` null; `team_abbr` from TeamAbbrev.
- Unmapped skill: [NEEDS CLARIFICATION: keep null `gsis_id`, skip, or fail? Default: keep null; count in `notes`; match-rate AT ≥95% on non-DST rows.]
- Do not invent stub players.

### Loader (CLI) — proposed

`python -m loader.dk_slate --csv path/to/DKSalaries.csv --season YYYY --week N [--trigger local|manual]`

- Thin in-repo CSV parse (stdlib / existing stack). Not `nfldfs`. Not draftkings.com.
- One transaction per slate: validate header, map, upsert, delete-missing, `load_runs`.
- [NEEDS CLARIFICATION: Ingest path — CLI file only this pass, or also a private upload endpoint/page? Default: **CLI file only** (data-load); upload UI later.]
- [NEEDS CLARIFICATION: Refresh — manual only vs anything scheduled? Default: manual / local only (Cosmo drops a new CSV).]

### HTTP API and pages

[NEEDS CLARIFICATION: Data-load only vs also read API / browse? Default: **data-load only** this pass (same pattern as F003).]

### Attribution and license

Historical public attribution remains the RotoGuru line (F003). Current-slate rows may be stored in Neon but must not appear as raw salary tables or CSV downloads on the public site. Do not claim affiliation with DraftKings; keep "Not affiliated with DraftKings." on any UI that mentions DK.

### Security

Same secrets rule as F001/F003. No DraftKings credentials. Never commit live unredacted contest CSVs without Cosmo's OK; committed fixtures must be tiny/synthetic or Cosmo-approved samples.

## Acceptance tests (draft)

- **AT1 (R1, R6)** Parse fixture CSV: required columns present; known player salary/id match.
- **AT2 (R2)** DST maps to `team_abbr`, `gsis_id` null.
- **AT3 (R2)** Skill player maps to the expected `gsis_id` when F001 data exists.
- **AT4 (R3)** Idempotent re-load; second run `rows_deleted=0`.
- **AT5 (R3)** Removed `dk_id` deleted on re-load.
- **AT6 (R4)** Bad header → prior slate rows unchanged, `load_runs.status=failed`, exit 1.
- **AT7 (R5)** `load_runs` row for `dk_classic_slate` with counts/notes.
- **AT8 (R2)** Match-rate AT (threshold from clarification).
- **AT9 (R7)** No draftkings.com fetch; no `nfldfs`.
- **AT10 (R8)** gitleaks clean; no passworded DB URLs; no live salary CSV secrets in repo.
- **AT11 (R1)** Only Classic multi-game rows accepted; Showdown-shaped input fails or is rejected clearly. [NEEDS CLARIFICATION: how to detect Showdown — roster positions / game count?]

## Non-goals

- Scraping draftkings.com.
- Historical RotoGuru backfill (F003).
- Showdown / single-game contests.
- FanDuel / other sites.
- Lineup optimizer / ILP (later feature).
- Pinning `nfldfs`.
- [If data-load only] Public API and HTML pages for current slate.
- Republishing DraftKings salary IP as a public downloadable dataset.

## Allowed dependencies

Existing F001/F003 stack. Stdlib CSV. Not allowed without asking: `nfldfs`, pandas, ORM, DraftKings API client, paid salary feeds.

## Open questions

1. ~~License / public exposure (R9).~~ Answered 2026-11-06: store in Neon; no public raw tables/CSV downloads; keep "Not affiliated with DraftKings."
2. ~~Slate identity.~~ Answered 2026-11-06: `--season` + `--week`; PK `(season, week, dk_id)`.
3. **Ingest path.** CLI only vs upload UI/API?
4. **Unmapped skill policy + match-rate.**
5. **Deliverable scope.** Data-load only vs API/pages?
6. **Showdown detection / rejection rule.**
7. **Constitution amendment** wording if storage is allowed.

## Decisions (from Cosmo via Groko, 2026-11-06)

- Feature next after F003: current-slate `DKSalaries.csv`.
- Never scrape draftkings.com; Cosmo uploads or pastes the official export.
- Optimizer is later (not this SPEC).
- **Q1:** Yes — store in Neon for personal/optimizer use. Do not publish raw salary tables or CSV downloads on the public site. Keep "Not affiliated with DraftKings."
- **Q2:** Slate key = Cosmo `--season` + `--week`; natural key `(season, week, dk_id)`.

## ADRs

- [ADR 0001: Stack and hosting](../../adr/0001-stack-and-hosting.md)
- [ADR 0002: nflverse load and refresh](../../adr/0002-nflverse-load-and-refresh.md)
- [ADR 0003: RotoGuru DK Classic salaries](../../adr/0003-rotoguru-dk-classic-salaries.md)
- [ADR 0004: Current-slate DK Classic CSV](../../adr/0004-dk-current-slate-csv.md) (Proposed)
