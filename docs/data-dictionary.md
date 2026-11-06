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
| season | int | no | Season Cosmo assigns on load |
| week | int | no | REG week Cosmo assigns on load |
| dk_id | text | no | DraftKings ID |
| name_raw | text | no | Name as exported |
| position_raw | text | no | Position column |
| roster_position_raw | text | no | Roster Position column |
| team_raw | text | no | TeamAbbrev |
| game_info_raw | text | yes | Game Info |
| salary | numeric | no | Salary |
| avg_points_per_game | numeric | yes | AvgPointsPerGame |
| gsis_id | text | yes | FK → players |
| team_abbr | text | yes | FK → teams when mapped |
| opponent_abbr | text | yes | Parsed when possible |
| game_id | text | yes | FK → games when unique |
| source_name | text | no | Filename or upload label |
| source_sha256 | text | no | Content hash |
| source_loaded_at | timestamptz | no | Load time |
| loaded_at | timestamptz | no | Row write time |

Readonly grants: same pattern as other tables (`READONLY_ROLE`).

