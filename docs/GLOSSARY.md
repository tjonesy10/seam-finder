# Glossary

| Term | Definition | Code / data name |
|---|---|---|
| nflverse | Open-source project publishing free NFL data files and loader libraries. | `nflverse-data` releases |
| nflverse-data release | A GitHub release in nflverse/nflverse-data holding one dataset's files (parquet, CSV) and a `timestamp.json`. | e.g. `stats_player`, `schedules` |
| nflreadpy | nflverse's Python loader library (MIT); allowed fallback, not the primary path. | `nflreadpy` |
| gsis_id | NFL player ID used by nflverse; our player key. Called `player_id` in the nflverse stats file. | `players.gsis_id`, `player_week_stats.gsis_id` |
| team abbreviation | Short team code; our team key. Includes historical codes (OAK, SD, STL). | `team_abbr`; `team`, `home_team`, `away_team`, `opponent_team` |
| game_id | nflverse game key, `{season}_{week}_{away}_{home}`. | `games.game_id` |
| season | NFL season year it starts in (the 2025 season's playoffs are in early 2026). | `season` |
| read-only role | The Postgres login the web app uses; it can only `SELECT`. Its name is set in the `READONLY_ROLE` Actions variable. | `READONLY_ROLE` |
| cold start | The wait (about a minute) when a sleeping Render free instance gets its first request. | n/a |
| secret | A credential (DB URL, key, token) stored only in GitHub Actions secrets or Render environment variables, never in the repo. | `DATABASE_URL` |
| week | Week number within a season; postseason weeks continue after the last regular-season week. | `week` |
| season type | REG (regular season) or POST (postseason). | `season_type` |
| game type | nflverse's finer game label: REG, WC, DIV, CON, SB. | `games.game_type` |
| standard scoring | Fantasy points with no points per reception, as computed by nflverse. | `fantasy_points` |
| PPR | Points per reception: standard scoring plus 1 point per catch, as computed by nflverse. | `fantasy_points_ppr` |
| placeholder row | A stats-file row named "Team" with no player ID; skipped by the loader. | `player_id IS NULL` in source |
| natural key | The source's own unique key for a row, used for upsert. | PKs in data-dictionary.md |
| upsert | Insert a row, or update it if its natural key already exists. | `INSERT ... ON CONFLICT DO UPDATE` |
| load run | One loader pass over one dataset (and season), recorded in `load_runs`. | `load_runs` |
| source version | The release's `last_updated` value at load time. | `load_runs.source_version` |
| refresh | A scheduled or manual load run of the current season plus teams and players. | `.github/workflows/refresh.yml` |
| backfill | A manual load run for a list of past seasons. | `workflow_dispatch` input `seasons` |
| attribution | The CC BY 4.0 credit line shown on every page. | page footer, `GET /api` |
| cold start | Wait while a spun-down free service starts again on the first request. | Render free web service |
| replacement level | Value of a freely available player at a position; used in part 3, not part 1. | (future) |
| DFS | Daily fantasy sports: pick a lineup under a salary cap for one slate; part 4, not part 1. | (future) |
| slate | The set of games one DFS contest covers; part 4, not part 1. | (future) |
| RotoGuru | Site publishing historical DFS weekly salary and points SCSV files. | rotoguru1.com |
| GID | RotoGuru player/defense identifier, unique within their files. | `dk_classic_salaries.rotoguru_gid` |
| DK Classic | DraftKings multi-game weekly salary-cap contest (not Showdown). | F003 / F004 |
| DST | Defense/special teams lineup slot; RotoGuru `Pos=Def`. | `pos_raw=Def` |
| DKSalaries.csv | Official DraftKings Classic salary export Cosmo downloads for a contest slate. | F004 source |
| dk_id | DraftKings player/defense identifier in `DKSalaries.csv`. | `dk_classic_slate.dk_id` |
| Current slate | The live or upcoming Classic contest week Cosmo is entering, as opposed to historical RotoGuru weeks. | F004 |
| Staged slate CSV | Cosmo-dropped `DKSalaries.csv` at the agreed path/secret/artifact the scheduled job loads; not fetched from DraftKings. | F004 schedule |




## F005–F008 terms

| Term | Definition | Code / data name |
|---|---|---|
| Live lobby capture | Unauthenticated bounded private DK Classic CSV retrieval; unofficial private experiment, not owner export or historical endpoint. | F005 / dk_lobby |
| Draft group | Native DK contest player-pool identifier; retains game/rules context, not equal to season/week or stable player identity. | draft_group_id |
| Artifact | Exact private bytes with source-specific SHA; BOM/CRLF and rejected evidence preserved, not only parsed values. | salary_artifacts |
| Observation | One capture/ingestion attempt and its timestamps, even when bytes are unchanged. | salary_observations |
| Capture runtime | Wall-clock `started_at`/`finished_at` and monotonic `duration_ms` for one private capture attempt. Not derived by subtracting clocks. | `salary_observations.duration_ms` |
| Source snapshot | One immutable source/path/group + artifact + parser/identity-metadata revision, not a union of weekly players. | salary_snapshots |
| Slate revision | Verified exact game/kickoff set plus roster/rules/cap identity; changed evidence yields another revision. Native groups need explicit equivalence evidence. | canonical_slate_key / slate_revision_sha256 |
| DFF | Daily Fantasy Fuel; acquired files are dated HTML-row-extraction salary/projection-player subsets, not complete DK exports. | dff_salaries |
| DFF player ID | Vendor-specific identifier, never presumed DK ID or GSIS ID. | dff_player_id |
| ppg_proj | DFF projected fantasy points, not actual realized points. | dff_salaries.ppg_proj |
| DKNFL archive | pureslurp/DKNFL original salary-export files; contains duplicate, holiday, alternate and mislabeled-path exports. | dknfl_salaries |
| Anchor snapshot | One coherent source snapshot defining a chosen pool's membership/salaries; never supplemented from other pools/snapshots. | anchor_snapshot_id |
| Alternative | A separately attributed equivalent source candidate, never a missing-player pool filler. | alternative_refs |
| Legacy unknown slate | F003 weekly evidence lacking verified exact slate fidelity; never a wildcard known-slate match. | legacy_unknown |
| Current adapter | F004 row-image copy of only currently retained rows, not recovered historical CSV snapshots. | adapter_current / raw_retained=false |
| Mapping version | Immutable interpretation/evidence version linking source entities/slates to verified canonical keys; does not mutate originals. | salary_interpretations.mapping_version |
| Selection batch | Atomic, reproducible private read selection at a cutoff; old batches remain pinned/queryable. | selection_id |
| Optimizer-ready | Row and entire anchor pool satisfy verified identity/slate/completeness and resolved-conflict checks, not merely a non-null GSIS ID. | optimizer_ready / pool_ready |
| Private salary surface | Single proposed read-only SQL view with provenance and flags; not an API or public table. | salary_private.dk_salary_unified |
