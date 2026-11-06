# Data dictionary: Seam Finder, Part 1

Status: READY (2026-11-05). Source facts measured from nflverse-data release files on 2026-11-05. Load rules: [ADR 0002](adr/0002-nflverse-load-and-refresh.md). Terms: [GLOSSARY.md](GLOSSARY.md).

Conventions: snake_case; column names match nflverse except where noted; `NOT NULL` only where the source had zero nulls for 2015-2026 or the loader sets the value. Every data table has `loaded_at timestamptz NOT NULL` (set by the loader on insert/update; not listed below).

Source files (prefix `https://github.com/nflverse/nflverse-data/releases/download/`):

| Table | File | Rows measured |
|---|---|---|
| teams | `teams/teams_colors_logos.parquet` | 36 |
| players | `players/players.parquet` | 24,864 |
| games | `schedules/games.parquet` (all seasons, filtered) | 3,300 for 2015-2026 |
| player_week_stats | `stats_player/stats_player_week_{season}.parquet` | 208,296 for 2015-2026 (2026 through week 8), of which 244 are team placeholder rows (skipped, see below) |

## teams

PK `team_abbr`. Includes historical abbreviations (OAK, SD, STL; both LA and LAR), so old games and stats resolve.

| Column | Type | Null | Source |
|---|---|---|---|
| team_abbr | text | PK | team_abbr |
| team_name | text | no | team_name |
| team_nick | text | no | team_nick |
| team_conf | text | no | team_conf |
| team_division | text | no | team_division |
| team_id | text | no | team_id (nflverse numeric id as text) |
| team_color | text | no | team_color (hex) |
| team_color2 | text | no | team_color2 (hex) |

Not loaded: color3/4 and all logo/wordmark URLs.

## players

PK `gsis_id`. Upsert-only (never deleted).

| Column | Type | Null | Source |
|---|---|---|---|
| gsis_id | text | PK | gsis_id |
| display_name | text | no | display_name |
| first_name | text | yes | first_name |
| last_name | text | yes | last_name |
| position | text | yes | position |
| position_group | text | yes | position_group |
| birth_date | date | yes | birth_date (string `YYYY-MM-DD`, parsed) |
| height | smallint | yes | height (inches) |
| weight | smallint | yes | weight (pounds) |
| college_name | text | yes | college_name |
| rookie_season | smallint | yes | rookie_season |
| last_season | smallint | yes | last_season |
| latest_team | text | yes | latest_team (no FK; may hold values outside `teams`) |
| status | text | yes | status (e.g. ACT, CUT, RES, DEV) |
| years_of_experience | smallint | yes | years_of_experience |
| draft_year | smallint | yes | draft_year (null = undrafted) |
| draft_round | smallint | yes | draft_round |
| draft_pick | smallint | yes | draft_pick |
| draft_team | text | yes | draft_team |
| pfr_id | text | yes | pfr_id |
| espn_id | text | yes | espn_id |
| pff_id | text | yes | pff_id |
| nfl_id | text | yes | nfl_id |
| esb_id | text | yes | esb_id |
| otc_id | text | yes | otc_id |
| is_stub | boolean | no | loader: true if created from a stats row because the player was missing from the players file |

Minimal player rows (a gsis_id seen in player_week_stats but missing from the players file) are inserted with `display_name` only; `first_name` and `last_name` stay null until the players file supplies them. The loader never derives them by splitting `display_name` (it breaks on suffixes like 'Jr.' and multi-word surnames).

Indexes: `(position)`, `(latest_team)`, `lower(display_name) text_pattern_ops` for name prefix search.

## games

PK `game_id` (format `{season}_{week:02}_{away}_{home}`, e.g. `2025_01_DAL_PHI`).

| Column | Type | Null | Source |
|---|---|---|---|
| game_id | text | PK | game_id |
| season | smallint | no | season |
| game_type | text | no | game_type: REG, WC, DIV, CON, SB |
| season_type | text | no | loader: `REG` if game_type = REG, else `POST` |
| week | smallint | no | week |
| gameday | date | no | gameday (string, parsed) |
| weekday | text | no | weekday |
| gametime | text | yes | gametime (`HH:MM` as published) |
| away_team | text | no | away_team, FK teams (`teams.team_abbr`) ON DELETE RESTRICT |
| home_team | text | no | home_team, FK teams (`teams.team_abbr`) ON DELETE RESTRICT |
| away_score | smallint | yes | away_score (null until played) |
| home_score | smallint | yes | home_score (null until played) |
| result | smallint | yes | result (home minus away) |
| total | smallint | yes | total |
| overtime | boolean | yes | overtime (0/1) |
| location | text | no | location (Home, Neutral) |
| roof | text | yes | roof |
| surface | text | yes | surface |
| stadium | text | yes | stadium |
| spread_line | numeric(4,1) | yes | spread_line |
| total_line | numeric(4,1) | yes | total_line |
| old_game_id | text | yes | old_game_id |
| pfr | text | yes | pfr (cross-site id) |
| espn | text | yes | espn (cross-site id) |

Indexes: `(season, season_type, week)`, `(home_team, season)`, `(away_team, season)`.

## player_week_stats

One row per player per game. PK `(gsis_id, season, week)`; unique `(gsis_id, game_id)`. Both were unique among rows with a player_id in every season 2015-2026. All positions are loaded.

Skipped: source rows with null `player_id`. These are placeholder rows named "Team" (one per season week, 21-22 per season; 244 in 2015-2026) that hold team-credited defensive numbers and zero fantasy points. The loader counts them in `load_runs.rows_skipped`.

| Column | Type | Null | Source |
|---|---|---|---|
| gsis_id | text | PK, FK players | player_id (renamed); FK `players.gsis_id` ON DELETE RESTRICT |
| season | smallint | PK | season |
| week | smallint | PK | week |
| season_type | text | no | season_type: REG, POST |
| game_id | text | no, FK games | game_id; FK `game_id` -> `games.game_id` ON DELETE RESTRICT |
| team | text | no, FK teams | team; FK `teams.team_abbr` ON DELETE RESTRICT |
| opponent_team | text | no, FK teams | opponent_team; FK `teams.team_abbr` ON DELETE RESTRICT |
| position | text | yes | position (null only on the skipped placeholder rows in 2015-2026; kept nullable) |
| position_group | text | yes | position_group |
| completions | smallint | no | completions |
| attempts | smallint | no | attempts |
| passing_yards | smallint | no | passing_yards |
| passing_tds | smallint | no | passing_tds |
| passing_interceptions | smallint | no | passing_interceptions |
| sacks_suffered | smallint | no | sacks_suffered |
| sack_fumbles_lost | smallint | no | sack_fumbles_lost |
| passing_2pt_conversions | smallint | no | passing_2pt_conversions |
| carries | smallint | no | carries |
| rushing_yards | smallint | no | rushing_yards |
| rushing_tds | smallint | no | rushing_tds |
| rushing_fumbles_lost | smallint | no | rushing_fumbles_lost |
| rushing_2pt_conversions | smallint | no | rushing_2pt_conversions |
| receptions | smallint | no | receptions |
| targets | smallint | no | targets |
| receiving_yards | smallint | no | receiving_yards |
| receiving_tds | smallint | no | receiving_tds |
| receiving_fumbles_lost | smallint | no | receiving_fumbles_lost |
| receiving_2pt_conversions | smallint | no | receiving_2pt_conversions |
| target_share | double precision | yes | target_share |
| special_teams_tds | smallint | no | special_teams_tds |
| fantasy_points | numeric(6,2) | no | fantasy_points (standard scoring, as computed by nflverse) |
| fantasy_points_ppr | numeric(6,2) | no | fantasy_points_ppr (PPR, as computed by nflverse) |

`game_id` -> `games.game_id` uses `ON DELETE RESTRICT`. If a games load would delete a game that still has stats rows, that games load fails and rolls back (last good data kept, `load_runs` status failed), per ADR 0002 failure handling. No cascading deletes.

Not loaded (addable later by a migration + loader column map): EPA, air yards, YAC, defense, kicking, punting, and the other ~110 source columns. Nullability above was checked on 2015-2026 rows that have a player_id; the loader checks it every run.

Indexes: `(season, season_type, week)`, `(team, season)`, `(game_id)`, `(season, position)`.

## load_runs

One row per dataset per season per run. Written by the loader only.

| Column | Type | Null | Notes |
|---|---|---|---|
| id | bigint identity | PK | |
| run_group | uuid | no | same value for every row from one loader invocation |
| dataset | text | no | `teams`, `players`, `games`, `player_week_stats` |
| season | smallint | yes | null for teams and players |
| status | text | no | `running`, `succeeded`, `failed` (check constraint) |
| trigger | text | no | `schedule`, `manual`, `local` |
| started_at | timestamptz | no | |
| finished_at | timestamptz | yes | null while running |
| source_url | text | no | release file URL |
| source_version | text | yes | `last_updated` from the release's `timestamp.json` |
| rows_read | integer | yes | rows in source for this dataset+season |
| rows_upserted | integer | yes | |
| rows_deleted | integer | yes | |
| rows_skipped | integer | yes | source rows not loaded by rule (e.g. null player_id) |
| notes | text | yes | e.g. count of stub players created |
| error | text | yes | set when failed |

Indexes: `(dataset, season, started_at desc)`, `(status)`.

The load_runs row is written in its own transaction (so a failure is recorded even though the data transaction rolled back).

## Migration plan

- Alembic, in `migrations/`. The build agent writes the migrations; this doc is the spec for them.
- `0001_initial`: create the five tables above, constraints, indexes, and a read-only role grant (`SELECT` on all tables) for the web app's role. Role names come from config, not the migration.
- Migrations run as the loader role, at the start of the refresh workflow (`alembic upgrade head`) and locally before tests.
- Adding stat columns later: one migration adds nullable columns, the loader column map adds the source names, and the next backfill fills them.
- Foreign keys use `ON DELETE RESTRICT`: `player_week_stats.game_id` -> `games.game_id`, `player_week_stats` -> `players` and -> `teams`, and `games` -> `teams`.
- No down-migrations needed for part 1 beyond Alembic's generated drop of `0001`.

## dk_classic_salaries (F003, READY)

Historical DraftKings NFL Classic weekly salaries and points from RotoGuru. PK `(season, week, rotoguru_gid)`. Load rules: [ADR 0003](adr/0003-rotoguru-dk-classic-salaries.md).

| Column | Type | Null | Source |
|---|---|---|---|
| season | smallint | PK | Year |
| week | smallint | PK | Week |
| rotoguru_gid | integer | PK | GID |
| name_raw | text | no | Name |
| pos_raw | text | no | Pos |
| team_raw | text | no | Team (RotoGuru code) |
| home_away | text | no | h/a |
| opponent_raw | text | no | Oppt |
| dk_points | numeric(8,2) | no | DK points |
| dk_salary | integer | no | DK salary (may be 0) |
| gsis_id | text | yes | mapped; FK players ON DELETE RESTRICT; null for Def and unmatched |
| team_abbr | text | yes | mapped; FK teams ON DELETE RESTRICT when set |
| opponent_abbr | text | yes | mapped opponent |
| game_id | text | yes | mapped REG game; FK games ON DELETE RESTRICT when set |
| source_url | text | no | fetch URL |
| source_fetched_at | timestamptz | no | fetch time |
| source_sha256 | text | no | hex digest of raw body |

Indexes: `(season, week)`, `(gsis_id, season, week)`, `(team_abbr, season, week)`.

## dk_classic_slate (F004, READY)

Current-slate DraftKings NFL Classic salaries from Cosmo's `DKSalaries.csv` export. PK `(season, week, dk_id)`. Load rules: [ADR 0004](adr/0004-dk-current-slate-csv.md).

| Column | Type | Null | Notes |
|---|---|---|---|
| season | smallint | no | Season Cosmo assigns on load |
| week | smallint | no | REG week Cosmo assigns on load |
| dk_id | text | no | DraftKings ID |
| name_raw | text | no | Name as exported |
| position_raw | text | no | Position column |
| roster_position_raw | text | no | Roster Position column |
| team_raw | text | no | TeamAbbrev |
| game_info_raw | text | yes | Game Info |
| salary | numeric(10,2) | no | Salary |
| avg_points_per_game | numeric(8,2) | yes | AvgPointsPerGame |
| gsis_id | text | yes | FK → players |
| team_abbr | text | yes | FK → teams when mapped |
| opponent_abbr | text | yes | Parsed when possible |
| game_id | text | yes | FK → games when unique |
| source_name | text | no | Filename or upload label |
| source_sha256 | text | no | Content hash |
| source_loaded_at | timestamptz | no | Load time |
| loaded_at | timestamptz | no | Row write time |

Indexes: `(season, week)`, `(gsis_id, season, week)`, `(team_abbr, season, week)`.

Readonly grants: same pattern as other tables (`READONLY_ROLE`).





## Proposed F005–F008 private salary contract (DRAFT; not deployed)

Governed by [ADR 0005](adr/0005-private-salary-capture-and-archives.md) and [ADR 0006](adr/0006-slate-safe-salary-unification.md). The following is a **proposed** additive schema, not a statement that migrations ran. Specs own behavior; this section owns shared shapes. All new relations are qualified `salary_private.<name>`. Existing F003/F004 keys and replacement loaders do not change.

### Types, privacy, bounds, and ownership

- UUIDs are generated in Python; timestamps are `timestamptz`, stored as instants and displayed in ET. Hashes are lowercase 64-character SHA-256 hex with a check constraint. IDs from publishers are text; no conversion between namespaces.
- `season smallint`, `week smallint` have range checks 1999–2100 and 1–22 when present; `season_type text` is REG/POST/UNKNOWN. Nullable source facts stay null. Salary is `numeric(10,2)`, nonnegative when parsed; positive integral salaries are required for an optimizer-ready row. Projection/rate fields use `numeric(12,4)` without conversion to actual points.
- Every new base table has `loaded_at timestamptz NOT NULL`; immutable rows are insert-only in loader code. Content tables use `ON CONFLICT DO NOTHING` only after comparing immutable fields; a conflicting value under the same key is an error. No delete-missing, truncate, cascade, or data purge. All FKs use `ON DELETE RESTRICT`.
- F005 owns the shared artifact/observation/snapshot/source-row foundation and lobby table; F006/F007 add one source table each; F008 adds interpretations, selection batches/rows, and the view. Sequential Alembic revisions are assigned by the engineer at build time, not presumed in this docs PR.
- Private schema owned by loader; revoke USAGE and relation/sequence grants from PUBLIC and the web `READONLY_ROLE`, including default privileges for the actual loader owner. Replace `loader/grants.py` blanket public grants/default grants with a public allowlist (`teams`, `players`, `games`, `player_week_stats`, `load_runs`, `dk_classic_salaries`). Explicitly revoke web/PUBLIC SELECT on `public.dk_classic_slate`; no SELECT-all-public refresh may regrant it. Existing nflverse/RotoGuru reads must still work. A configured, separately approved optimizer read role receives only schema USAGE and SELECT on `dk_salary_unified`, no writes or public-web membership.
- 5 MiB/object, 64 MiB/invocation raw bytes, 128 MiB cumulative private artifact bytes, 512 MiB database-size safety guards; also respect the lower verified current free allowance. `pg_total_relation_size` includes indexes/TOAST and `pg_database_size` checks overall use. Serial ingestion lock makes guard checks race-safe. These budgets are proposed limits, not Neon pricing facts. Exceeding any guard fails before publishing; no automatic eviction. Prefix-only diagnostics for oversized HTTP bodies are marked truncated and never count as a retained artifact/successful snapshot.

### salary_artifacts — exact private bytes

| Field | Type / rule |
|---|---|
| artifact_id | bigint identity PK |
| source | text NOT NULL: `dk_lobby`, `dff`, `dknfl`, `f003_adapter`, `f004_adapter`, `control` |
| sha256 | text NOT NULL; hash of exact stored bytes; UNIQUE `(source, sha256)` |
| body | bytea NOT NULL; exact bytes, no newline/BOM normalization; ≤5 MiB |
| byte_count | integer NOT NULL, equals octet_length(body) |
| media_type, artifact_kind | text NOT NULL; kind `csv`, `lobby_json`, `rules_json`, `html_gzip`, `manifest`, `mapping`, `adapter_row_image`, `rejected_body` |
| stored_at | timestamptz NOT NULL; storage time, not publisher time |

Hash/length verified in application and tested by readback. A DFF CSV is explicitly an HTML-row extraction, not original DK CSV. Gzip evidence is retained as received gzip bytes (no re-compression); its hash refers to those bytes. No unrelated research HTML, login, or account/contest-entry payload is ingested. `adapter_row_image` is an exact serialized local row image, **not** original downloaded CSV bytes.

### salary_observations — every capture/load attempt

| Field | Type / rule |
|---|---|
| observation_id | UUID PK, new for every attempted file/capture, including unchanged bytes |
| load_run_id | bigint NOT NULL FK `public.load_runs.id` (live column is bigint identity, not integer) |
| source | text NOT NULL, same source vocabulary as artifacts |
| requested_at | timestamptz NOT NULL; when the attempt was requested. Not the elapsed-time start |
| started_at | timestamptz NOT NULL; wall-clock start of the attempt. Distinct from requested_at and from public `load_runs.started_at` |
| finished_at | timestamptz NULL; wall-clock time of the in-process terminal write. Null when the attempt is still running or was interrupted before that write |
| duration_ms | integer NULL, `>= 0` when present; monotonic elapsed milliseconds between start and the terminal write. Never generated, repaired, or backfilled from `finished_at - started_at` or from `load_runs` clocks. Null when the monotonic interval was not durably stored |
| fetched_at, source_published_at | nullable timestamptz; fetched only for a real HTTP retrieval; publisher time only with evidence |
| observed_at | timestamptz NOT NULL; receipt/ingest time; archives must not present it as salary publication time |
| source_url, original_path | nullable text; preserve original repository URL/path, including pinned upstream commit |
| artifact_id, snapshot_id | nullable FKs to artifacts/snapshots, linked when available; no snapshot link on rejected parse |
| metadata | jsonb NOT NULL; exact manifest row, corrected labels, original labels, parser version, auxiliary artifact IDs, request attempt statuses, response content type/status, provenance uncertainty |
| status | text NOT NULL: running/succeeded/failed/rejected/skipped |
| reason_code, error_private | nullable text; bounded sanitized internal diagnostics, never credentials |

Indexes `(source, observed_at DESC)`, `(snapshot_id, observed_at DESC)`, `(load_run_id)`. An identical fetch still has a new observation and `load_runs` attempt; it does **not** duplicate parsed salary rows. Retry statuses are retained inside that observation. A successful repeated A→B→A fetch links the A snapshot again; as-of selection follows observation chronology, not the snapshot's first creation time.

F005 capture attempts always write `started_at`. A terminal in-process attempt also writes `finished_at` and `duration_ms` from a monotonic timer (`time.monotonic` or equivalent), including success, fetch failure, validation failure, off-season skip, and repeated identical content. `snapshot_id` links the attempt to its snapshot when one is published or reused; that snapshot's source rows are the linked rows. Attempts with no snapshot keep `snapshot_id` null and still store timing when the database is available. Public `load_runs.started_at`/`finished_at` may hold compatible wall times and must not be subtracted to produce elapsed time. Public notes, errors, and logs contain reason codes and counts only. A crash before the terminal timing write leaves `finished_at` and `duration_ms` null. Recovery must not invent them or mark the attempt completed. If no row was committed, do not claim one exists. The columns live on the shared observation table. F005 capture is the required producer of monotonic `duration_ms` (F005 R9). Other features must not compute a duration by subtracting timestamps if they write the column; leaving `duration_ms` null is acceptable for non-capture archive observations. Recovery never fabricates a missing duration.

### salary_snapshots — immutable parsed unit, not a season/week pool

| Field | Type / rule |
|---|---|
| snapshot_id | UUID PK |
| source, artifact_id | text + FK NOT NULL |
| parser_version, metadata_sha256 | text NOT NULL; version identifies deterministic parser logic |
| source_snapshot_key | text NOT NULL; DK draft group for live, archive original URL/path identity otherwise |
| season, season_type, week | corrected nullable season/week and required season_type |
| draft_group_id | nullable text; known for F005; unknown is null, never synthesized |
| games | jsonb NOT NULL; sorted entries `{away,home,kickoff_at,game_id?}`, unknown kickoff/game stays null; never infer absent games from player subset |
| rules | jsonb NOT NULL; `{rules_id?,roster_slots?,salary_cap?,evidence_artifact_id?}`; unknown fields null |
| game_set_sha256, rules_sha256 | nullable text; filled only when complete/verified, distinct from raw artifact hash |
| source_pool_kind | text NOT NULL: full_export/subset/legacy_unknown/adapter_current |
| metadata | jsonb NOT NULL; dates, correction evidence, original labels, headers, row counts, completeness claims, auxiliary artifact references; `raw_retained` boolean |
| created_at | timestamptz NOT NULL; not original source publication time |

UNIQUE `(source, source_snapshot_key, artifact_id, parser_version, metadata_sha256)`. Metadata hash includes identity-relevant group, corrected season/type/week, game/kickoff/rules evidence and manifest facts, but excludes ingestion/retrieval timestamps so identical content and identity replays reuse parsed rows. Two source paths sharing bytes still have separate snapshot identities and observations. Index `(source, season, season_type, week)`, `(draft_group_id)`, `(game_set_sha256, rules_sha256)`.

No slate verification is implied merely by this table existing. A changed kickoff or rules set produces a new metadata hash/revision. Source rows remain under their original snapshot even if later interpretations correct labels.

### salary_source_rows — lossless row ledger

PK `(artifact_id, parser_version, row_number)`; artifact FK, parser_version text, 1-based data `row_number integer > 0` (CSV logical record, not physical line), `raw_fields jsonb NOT NULL` storing original ordered header/value pairs (not a lossy dict), `parse_status text NOT NULL` (`parsed`/`rejected`), `reason_codes jsonb NOT NULL`. Header bytes, quoting, CRLF, malformed unparseable remainder, and original order are recoverable from the artifact. Byte offsets may be recorded but are not required. For a wholly unreadable CSV keep the artifact and rejected observation; do not invent row counts or ledger rows. Same bytes/parser version reuse ledger entries. A rejected blank-name/blank-salary record has a row ordinal and reason even though it has no normalized salary.

### Separate source tables

All three have PK `(snapshot_id, row_number)` with snapshot FK and `(artifact_id, parser_version, row_number)` FK to source-row ledger. `artifact_id`, `parser_version` match their snapshot. Shared fields: `row_status text NOT NULL` (`valid`/`rejected`), `reason_codes jsonb NOT NULL`, `salary numeric(10,2) NULL`, and raw identifying fields below. The shared schema is an evidence-retention superset: a parseable row can store a null salary plus its raw token and reason, and no unique player-ID constraint erases duplicate source rows. Source tables are filled only when that source publishes a snapshot. A null salary in the ledger or in a source row does not by itself make the snapshot usable or optimizer-ready. F005 does not publish `dk_lobby_salaries` when any salary is invalid. F006 and F007 may publish a parsed non-ready snapshot that includes rejected rows only where their SPECs say so.

| Table | Additional fields |
|---|---|
| dk_lobby_salaries | `dk_id text`, `name_raw text`, `position_raw text`, `roster_position_raw text`, `team_raw text`, `game_info_raw text`, `avg_points_per_game numeric(12,4)`, `status_raw text`; raw `Name + ID` and extras also retained in ledger |
| dff_salaries | `dff_player_id text`, `start_date date`, `week_raw text`, `name_raw text`, `position_raw text`, `pos_alt_raw text`, `team_raw text`, `opponent_raw text`, `location_raw text`, `ppg_proj numeric(12,4)`; other source fields untouched in ledger |
| dknfl_salaries | same DK fields as lobby except optional status; original publisher is `pureslurp/DKNFL` with upstream commit/URL in observations, not an official owner export |

Indexes per table `(snapshot_id, row_status)`, native ID (`dk_id` or `dff_player_id`) plus `snapshot_id`. These rows deliberately do not embed mutable identity guesses; F008 records normalized mapping separately. Exact duplicate source rows are retained, marked duplicates during interpretation, and must not become duplicate optimizer entities.

### F008 salary_interpretations

Append-only per-row or per-snapshot evidence-backed interpretations. `interpretation_id UUID PK`, `snapshot_id UUID FK`, `row_number integer NULL` (null = slate-level), `mapping_version text NOT NULL`, `evidence_sha256 text NOT NULL`, `evidence_artifact_id bigint FK NOT NULL`, `status text NOT NULL` (`verified`/`unresolved`/`ambiguous`/`rejected`/`legacy_unknown`), `entity_key text NULL` (`player:<gsis_id>` or `dst:<team_abbr>`), `gsis_id text FK public.players NULL`, `team_abbr text FK public.teams NULL`, `game_id text FK public.games NULL`, `canonical_slate_key text NULL`, `slate_revision_sha256 text NULL`, `effective_at timestamptz NULL`, `details jsonb NOT NULL`, `created_at timestamptz NOT NULL`. Details include match method, candidate IDs, author/rationale, games/rules/draft-group equivalence evidence, corrected metadata, effective-time basis, duplicate status, and completeness status. Partial unique indexes: `(snapshot_id, row_number, mapping_version, evidence_sha256)` WHERE row_number IS NOT NULL and `(snapshot_id, mapping_version, evidence_sha256)` WHERE row_number IS NULL. Index `(canonical_slate_key, slate_revision_sha256)`, `(entity_key)`. Validate non-null row_number refers to a source row or adapter row image; malformed or cross-snapshot references fail before publication.

A verified slate revision hashes canonical JSON of NFL, DK, Classic, season/type/week, sorted exact game+kickoff set, roster slots/salary cap and compatible rule identifiers. Keep draft group separately. Equivalent different native draft groups require an explicit equivalence record in details with both IDs and rule evidence; same hash alone is not permission to combine. `legacy_unknown` is a separate namespace, not a wildcard.

### F008 salary_selection_batches and salary_selection_rows

`salary_selection_batches`: `selection_id UUID PK`, `selection_scope text NOT NULL`, `cutoff_at timestamptz NOT NULL`, `mapping_version text NOT NULL`, `input_sha256 text NOT NULL`, `load_run_id bigint FK NOT NULL`, `committed_at timestamptz NOT NULL`, `summary jsonb NOT NULL`. UNIQUE `(selection_scope, cutoff_at, mapping_version, input_sha256)`; index `(selection_scope, committed_at DESC, selection_id)`. Insert only complete batches in the publish transaction. Reruns reuse an identical batch but record a new load attempt.

`salary_selection_rows`: PK `(selection_id, snapshot_id, row_number)`; FKs to batch/snapshot; `interpretation_id UUID FK NULL`, `slate_interpretation_id UUID FK NULL`, `observation_id UUID FK NULL`, `anchor_snapshot_id UUID FK NULL`, `canonical_slate_key text NULL`, `slate_revision_sha256 text NULL`, `entity_key text NULL`, `is_selected boolean NOT NULL`, `pool_ready boolean NOT NULL`, `optimizer_ready boolean NOT NULL`, `salary_selected numeric(10,2) NULL`, `quality_flags jsonb NOT NULL`, `alternative_refs jsonb NOT NULL` (references contain snapshot/row/interpretation/observation IDs, salary and eligibility; not copies without provenance). Index `(selection_id, canonical_slate_key, slate_revision_sha256)`, `(selection_id, entity_key)`. Partial UNIQUE `(selection_id, canonical_slate_key, slate_revision_sha256, entity_key)` WHERE is_selected AND entity_key IS NOT NULL. All selected members for one pool share one anchor snapshot ID. Any accepted disagreement resolution is referenced by evidence hash in flags/details; no raw source updates.

Adapters supply immutable `adapter_row_image` artifacts/ledger/snapshots first. F003 row key remains `(season, week, rotoguru_gid)` and `legacy_unknown`; DK actual points remain source-specific. F004 only reads current rows grouped by source SHA and actual available game/roster evidence. Neither adapter claims original retained bytes, historical replaced rows, or source fetch times. Adapter snapshot identity hashes the current ordered row image plus existing provenance so a rerun cannot fabricate history or accidentally join unrelated revisions. F003/F004 source tables are never rewritten.

### dk_salary_unified — one private read surface

A SQL view joining the above batch rows to immutable source values, mappings, and attribution; not a public endpoint. One row per candidate source row per selection batch, including flagged rejected/unresolved/legacy/alternative rows, so absence is not hidden. At minimum return:

`selection_id, selection_scope, is_current, cutoff_at, source, source_snapshot_id, source_row_number, artifact_sha256, raw_retained, observation_id, observed_at, fetched_at, effective_at, draft_group_id, season, season_type, week, canonical_slate_key, slate_revision_sha256, games, rules, entity_key, gsis_id, team_abbr, game_id, dk_id, dff_player_id, salary_source, salary_selected, roster_position_raw, source_pool_kind, anchor_snapshot_id, is_selected, pool_ready, optimizer_ready, quality_flags, alternative_refs, parser_version, mapping_version, evidence_sha256, source_url, original_path, attribution`.

`is_current` is the latest committed batch for a selection_scope, ordered `(committed_at DESC, selection_id DESC)`. Consumers should pin a selection_id; old batches remain queryable. Native ID columns only filled for their actual publisher. No cross-source COALESCE of player IDs. No generalized points column: DFF ppg_proj is a projection, DK AvgPointsPerGame a source average, RotoGuru dk_points source actuals; do not treat any as interchangeable. Exact attribution is source-specific: DFF = "Salary/projection subset via Daily Fantasy Fuel (dailyfantasyfuel.com). Not affiliated with DraftKings."; DKNFL = "Archived DraftKings salary export via pureslurp/DKNFL (GitHub). Not affiliated with DraftKings."; F004 = "Owner-supplied DraftKings Classic export. Not affiliated with DraftKings."; F005 = "Unauthenticated DraftKings Classic lobby capture (private experiment). Not affiliated with DraftKings."; F003 keeps its existing exact line.

### Transaction and audit contract for all four features

1. Create `public.load_runs` running in its own transaction. Dataset: `dk_lobby_salaries`, `dff_salaries`, `dknfl_salaries`, or `dk_salary_unified`. Use existing status values running/succeeded/failed. `load_runs.trigger` has no check constraint. The live dictionary documents nflverse triggers as `schedule`, `manual`, and `local`. F004's CLI persists the literal `scheduled` and must not be changed. New F005–F008 CLIs store `schedule`/`manual`/`local` and may accept the input alias `scheduled` only by storing `schedule`. Store week/snapshot/count summaries as sanitized notes; do not add a fictitious load_runs.week column. `source_url` is a safe fixed dataset label or public origin, not a private path or signed URL. Publicly readable notes/error contain only stable reason codes and counts; raw diagnostics stay private. Do not store `duration_ms` on public `load_runs`.
2. Serial advisory transaction lock for shared storage budget checks and artifact insertion. Retain exact bounded artifacts + observation in a durable transaction **before** normalization. An invalid parser/header leaves these retained, marks failed/rejected observation, but publishes no new usable snapshot. Transient DB outage can prevent logging; exit nonzero, emit only a reason code, never claim a durable failed audit row exists if DB is unreachable.
3. Parse in memory and durably insert any parseable source-row ledger in an evidence transaction before semantic validation (same artifact/parser rows compare-and-reuse). Validate, then insert snapshot/source-table records in one normalized transaction per file only when that source's promotion rule allows a snapshot. F006/F007 process manifest entries sorted by original path; good prior files persist, failed file rolls back normalized writes, continue remaining independent files, overall nonzero if any failed. No network archive refetch; missing staged files fail clearly. The ledger retains parseable rejected rows, including a malformed salary as a null salary plus raw token and reason, whether or not a snapshot is published. Per-source validity rules govern promotion. F005 is stricter: any invalid salary rejects the usable snapshot; raw artifact, observation, and parseable ledger remain, and no `dk_lobby_salaries` rows are published for that capture. F006 and F007 may retain a parsed non-ready snapshot and rejected rows when their SPECs explicitly allow it. Successful parsing is not optimizer-ready completeness. F008 cannot bypass `pool_ready` or `optimizer_ready`, and it must not synthesize an anchor from F005 evidence that has no usable snapshot. File-fatal conditions are the ones each SPEC names as file-fatal.
4. Finalize private observation and sanitized load_runs audit; a crash can leave running attempts. Record run_group/observation IDs before data work and finalize the snapshot link/status in the same data commit; public audit finalization may be retried without duplicating data. On restart reconcile an existing running attempt only with matching durable commit evidence, else mark interrupted/failed and start a new attempt. Never infer success from elapsed time. Never fill `duration_ms` by subtracting wall clocks. If the monotonic interval was not durably stored, leave `duration_ms` and `finished_at` null rather than fabricating completion. An unreachable database exits nonzero and is not evidence that a timing row exists.
5. F008 builds a new batch locally then inserts its batch+all rows atomically. A failure leaves old current selection unchanged; artifacts, mappings and source tables remain unchanged. Lock publication per selection_scope, use deterministic tie breakers, and reuse identical unique batch keys on concurrent repeats.
