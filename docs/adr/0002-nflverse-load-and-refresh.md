# ADR 0002: nflverse source, idempotent load, and refresh

## Status

Proposed (2026-11-05)

## Context

Cosmo chose free public nflverse data: players, teams, weekly player stats, and schedules with results. Facts gathered 2026-11-05:

- **Files.** nflverse publishes each dataset as GitHub release assets in [nflverse/nflverse-data](https://github.com/nflverse/nflverse-data/releases), as parquet and CSV:
  - `players/players.parquet`: 24,864 rows, one per player, key `gsis_id` (no nulls, no duplicates).
  - `teams/teams_colors_logos.parquet`: 36 rows, key `team_abbr`; includes historical abbreviations (OAK, SD, STL, and both LA and LAR).
  - `schedules/games.parquet`: one file for all seasons since 1999 (7,548 rows; 3,300 for 2015-2026), key `game_id`. Unplayed games have null scores.
  - `stats_player/stats_player_week_{season}.parquet`: one file per season, 150 columns, 17,362-19,422 rows per full season 2015-2025; 2026 through week 8 has 8,428. 244 rows (2015-2026) have a null `player_id`: placeholder rows named "Team" holding team-credited defensive numbers. Among the rest, `(player_id, season, week)` is unique and `(player_id, game_id)` is also unique. Every non-null `player_id` is in players, every `game_id` in games, every team in teams (checked for 2015-2026).
  - Each release has `timestamp.json` with `last_updated` (e.g. `"2026-11-05 09:16:33 EST"` for stats).
- **Client library.** [nflreadpy](https://github.com/nflverse/nflreadpy) (MIT) wraps these same URLs (`load_players`, `load_teams`, `load_schedules`, `load_player_stats(summary_level="week")`) and returns Polars frames. Its README marks it experimental.
- **Update cadence** ([nflverse data schedule](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html)): player stats update nightly after game days in season; stat corrections land Monday-Wednesday, so data is cleanest by Thursday; schedules update every 5 minutes in season. Players and teams cadence is not stated (release timestamps on 2026-11-05: players 2026-11-04, teams 2026-03-27).
- **License.** nflverse-data's [LICENSE.md](https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md) is CC BY 4.0. nflreadpy's README: "The majority of all nflverse data available (ie all but the FTN data as of July 2025) is broadly licensed as CC-BY 4.0, and the FTN data is CC-BY-SA 4.0". nflreadr's [Terms of Use](https://github.com/nflverse/nflreadr#terms-of-use): "NFL data accessed by this package belong to their respective owners, and are governed by their terms of use." No dataset-specific license or required attribution wording was found for our four datasets, so they carry the repo's CC BY 4.0 (best reading, not a per-file statement). Schedules are maintained in [nflverse/nfldata](https://github.com/nflverse/nfldata) and players in [nflverse/nflverse-players](https://github.com/nflverse/nflverse-players); nfldata has no license file (GitHub API: not found); nflverse-players has only an R-style stub ("YEAR: 2024 / COPYRIGHT HOLDER: Sebastian Carl") that GitHub reads as "Other". The published release files sit in the CC BY 4.0 nflverse-data repo, which is what we rely on. We use no FTN data.

## Decision

1. **Source.** Download the four release parquet files directly over HTTPS and read them with Polars. Record the release's `timestamp.json` `last_updated` as the source version. nflreadpy is an allowed fallback, pinned, if the URLs move.
2. **Scope per run.** Teams and players: whole file. Games and player week stats: the requested seasons (default: the current season). Backfill passes a season list.
3. **Idempotent load.** For each (dataset, season) in one transaction: upsert every source row on its natural key (`INSERT ... ON CONFLICT (key) DO UPDATE`), then delete rows for that season whose keys were not in the batch (so dropped or re-keyed source rows go away). Teams and players are upsert-only (never deleted, since other rows reference them). Re-running with the same source gives the same table contents.
4. **Validation before writing.** Required columns present; keys non-null and unique; season and week in range; `season_type` in {REG, POST}; foreign keys resolvable. Stats rows with null `player_id` (the "Team" placeholder rows) are skipped and counted. A stats row whose player is missing from players gets a minimal players row (gsis_id, display name, position from the stats file) and is counted in the run notes. Any other failure aborts that dataset+season.
5. **load_runs.** One row per dataset+season per run: status (`running`, `succeeded`, `failed`), started/finished times, source URL, source version, rows read/upserted/deleted/skipped, trigger (`schedule`, `manual`, `local`), error text. Columns in [data-dictionary.md](../data-dictionary.md#load_runs).
6. **Schedule.** GitHub Actions `refresh.yml`: cron daily at 11:00 UTC (6:00 AM ET in winter, 7:00 AM ET in summer), loading the current season, plus `workflow_dispatch` with a `seasons` input. A run also loads teams and players. Off-season runs are cheap and catch roster/player updates.
7. **Failure handling.** A failed dataset+season rolls back its own transaction, so the last good data stays. The run marks it `failed` with the error, continues with datasets that don't depend on it (a failed games load skips that season's stats), and exits non-zero so GitHub emails the repo owner. Downloads retry 3 times with backoff. No partial writes.
8. **Attribution.** Every HTML page footer and the API root (`GET /api`) carry: "Data: nflverse (nflverse-data), licensed CC BY 4.0. Changes: subset of columns, loaded into a database. Not affiliated with or endorsed by the NFL or nflverse. NFL data belong to their respective owners." with links to `https://github.com/nflverse/nflverse-data` and `https://creativecommons.org/licenses/by/4.0/`. The repo README carries the same text.
9. **Not displayed.** Team logo and player headshot URLs are not loaded or shown; the images are NFL/ESPN assets and trademarks, not nflverse's to license.

## Reasoning

- Direct release files are what nflreadpy itself fetches; skipping the experimental wrapper removes a dependency and gives the source version for free.
- Reloading a whole current season each run is small (under 20,000 stats rows) and picks up stat corrections without tracking which weeks changed.
- Upsert plus delete-missing per season in one transaction is the simplest load that is both idempotent and correct when nflverse removes or fixes rows.
- Daily runs cover the nightly stats update and the Monday-Wednesday corrections; Thursday's run sees the corrected week.

## Rejected alternatives and why

- **Truncate and reload everything each run**: simple, but leaves the site empty or inconsistent if the run dies midway, and rewrites unchanged history daily.
- **Insert-only by week**: misses stat corrections to earlier weeks.
- **Upsert only (no delete)**: rows removed upstream would linger forever.
- **nflreadpy as the primary path**: experimental lifecycle, local caching adds behavior to reason about, and it doesn't expose the release timestamp.
- **CSV instead of parquet**: about 10x larger per stats season and loses types.
- **Scraping NFL.com or other sites**: terms of use, fragility, and no need.

## Consequences

- Data is at most about a day old in season; stat corrections appear by the Thursday run.
- `games` has nflverse's `game_type` (REG, WC, DIV, CON, SB); we add `season_type` (REG or POST) so games and stats filter the same way.
- If nflverse changes file names or columns, validation fails loudly and the site keeps the last good data.
- Public sharing depends on CC BY 4.0 attribution being shown and on the unclear status of underlying NFL rights; flagged as an open question in the [F001 SPEC](../features/F001-data-prototype/SPEC.md#open-questions).
