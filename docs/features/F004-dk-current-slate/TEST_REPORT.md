# F004 test report

Date: 2026-11-06. Scope: `dk_classic_slate` migration, `python -m loader.dk_slate`, GitHub Actions cron plus `workflow_dispatch`, AT1–AT13. No read API and no browse page. Historical RotoGuru loading is unchanged.

## Results

| AT | Result | Evidence |
|---|---|---|
| AT1 | PASS | `tests/test_dk_slate.py::test_at1_parse_fixture_salary_and_id`. Fixture `tests/fixtures/dk_slate/classic.csv` has every required column plus an ignored extra column. Pat Sample id `1001` is salary `7000.00`. A reversed header and `$7,000` parse to the same id and salary. Loaded row keeps `team_raw=ne` and `team_abbr=NE`. Blank `AvgPointsPerGame` is null. |
| AT2 | PASS | `test_at2_dst_maps_to_team_and_null_gsis`. Chiefs `position_raw=dst`, `team_abbr=KC`, `gsis_id` null, `opponent_abbr=NE`, `game_id=2026_10_NE_KC`, salary `3000.00`. |
| AT3 | PASS | `test_at3_skill_player_maps_to_gsis_id`. Pat Sample maps to `00-0001001` from the NE week-10 stat, not the other Pat Sample whose `latest_team` is NE. Fallback Sample maps to `00-0001004` from `latest_team` only. Run Sample stays null. |
| AT4 | PASS | `test_at4_second_load_is_idempotent`. Second run `rows_deleted=0`. Row equality ignores `loaded_at` and `source_loaded_at`. |
| AT5 | PASS | `test_at5_removed_dk_id_is_deleted`. Dropping dk_id `1002` deletes that row (`rows_deleted=1`), updates `1001` to `7100.00`, and leaves week 11. |
| AT6 | PASS | `test_at6_bad_header_keeps_rows_and_exits_1`. `python -m loader.dk_slate` returns 1, `load_runs.status=failed`, prior rows unchanged, error contains `missing required column`. |
| AT7 | PASS | `test_at7_load_runs_record`. Dataset `dk_classic_slate`, season 2026, trigger, `source_url=file:classic.csv`, sha256 in `source_version`, counts set. Notes are `week=10; unmapped_skill=1`. |
| AT8 | PASS | `test_at8_non_dst_match_rate_is_at_least_95_percent`. 19/20 non-DST rows have `gsis_id` (95%). The unmatched skill row stays null. DST is not in the denominator and stays unmapped. Notes `unmapped_skill=1`. |
| AT9 | PASS | `test_at9_no_nfldfs_or_draftkings_fetch` and `tests/test_dk_classic.py::test_at9_no_nfldfs_or_draftkings_in_production_code`. `pyproject.toml`, `loader`, `web`, `migrations`, and workflows have no `nfldfs` and no `draftkings.com`. The artifact helper calls `api.github.com` only. |
| AT10 | PASS | `test_at10_gitleaks_and_workflow_do_not_leak_secrets` and `tests/test_refresh.py::test_at26_no_secrets_in_repo`. gitleaks v8.30.1 exit 0. The slate workflow does not `printenv`, `echo` the database URL, or `echo` `DK_SLATE_CSV`. The committed fixture is four synthetic rows. |
| AT11 | PASS | `test_at11_showdown_is_rejected`. A `CPT` roster with two games, and a single `Game Info` with no captain, each exit 1. Stderr and `load_runs.error` contain `Classic-only`. Prior slate rows stay. |
| AT12 | PASS | `test_at12_scheduled_workflow_and_missing_file`. `.github/workflows/dk-classic-slate.yml` has `cron: "0 15 * * 2"`, `workflow_dispatch`, and `python -m loader.dk_slate` with `--trigger scheduled` or `manual`. Season and week come from inputs or `DK_SLATE_SEASON` / `DK_SLATE_WEEK`. Staging order is secret `DK_SLATE_CSV`, then `csv_path` / `DK_SLATE_CSV_PATH`, then artifact `DK_SLATE_ARTIFACT` via `fetch_staged_artifact`. A missing path exits 1, `load_runs.status=failed`, trigger `scheduled`, prior rows unchanged. `bash -n` on the load step passed. |
| AT13 | PASS | `test_at13_no_public_salary_endpoint`. `web/` has no `dk_classic_slate` or `DKSalaries` reference. API and page lists have no salary or slate route. `GET /api/dk-classic-slate`, `/api/salaries`, `/dk-salaries.csv`, and `/slate` return 404. |

Supporting checks, not separate ATs: duplicate `dk_id` raises `duplicate key: dk_id`; an unknown `TeamAbbrev` fails the load and keeps the prior slate; week 19 and season 1800 exit 1 before a load. `tests/test_schema.py` checks the new columns, `numeric(10,2)` salary, `numeric(8,2)` average, primary key `(season, week, dk_id)`, three indexes, and `ON DELETE RESTRICT`. The read-only role can `SELECT` from `dk_classic_slate`.

## Commands

```text
ruff check loader web tests migrations
All checks passed!

pytest -q
134 passed, 2 skipped, 1 warning in 8.76s
```

The skips are the nflverse network test and the live RotoGuru test unless `RUN_NETWORK_TESTS=1`.

## Loader proof (local Postgres)

Teams and one Pat Sample week-10 stat were inserted for this proof. Fallback Sample was not inserted, so that skill row stays unmapped here. AT3 covers the fallback match.

```text
$ python -m loader.dk_slate --csv tests/fixtures/dk_slate/classic.csv --season 2026 --week 10 --trigger local
dk_classic_slate season=2026 week=10 status=succeeded

 dk_id | name_raw        | position_raw | team_abbr | opponent_abbr | game_id        | salary  | avg    | gsis_id
 1001  | Pat Sample      | QB           | NE        | KC            | 2026_10_NE_KC  | 7000.00 | 21.50  | 00-0001001
 1002  | Run Sample      | WR           | PHI       | DAL           | 2026_10_DAL_PHI| 6500.00 |        | 
 1003  | Chiefs          | dst          | KC        | NE            | 2026_10_NE_KC  | 3000.00 | 8.10   | 
 1004  | Fallback Sample | RB           | DAL       | PHI           | 2026_10_DAL_PHI| 5500.00 | 9.00   | 

 status    | rows_read | rows_upserted | rows_deleted | notes
 succeeded |         4 |             4 |            0 | week=10; unmapped_skill=2
```

## Mutation testing

Tool: [unclebob/mutator](https://github.com/unclebob/mutator) with [unclebob/crapper](https://github.com/unclebob/crapper) checked out beside it. Command: `mutator --changed --max-workers 1 --test-command "python3 -m pytest -q"` from the repo root. One worker, because the suite shares one Postgres. Changed Python files: `loader/dk_slate.py`, `loader/tables.py`, `migrations/versions/0003_dk_classic_slate.py`.

| File | Killed | Survived | Uncovered | Sites |
|---|---:|---:|---:|---:|
| `loader/dk_slate.py` | 48 | 49 | 7 | 104 |
| `loader/tables.py` | 2 | 0 | 0 | 2 |
| `migrations/versions/0003_dk_classic_slate.py` | 0 | 0 | 14 | 14 |
| Total | 50 | 49 | 21 | 120 |

Score on executed mutants: 50/99 (50.5%). Process exit 3 (at least one survivor). Advisory only. Acceptance tests above stay PASS.

Survivors, grouped. PASS means the mutant does not change a result these tests check. UNKNOWN means that branch was not asserted, so the mutant's effect is not shown. None of these are treated as an AT failure.

| Result | Where | Why |
|---|---|---|
| PASS | `_number` lines 79–82 (`0`/`1`, `==`, `+`/`-`, `>`/`>=`) | Same integer-digit count as F003. Fixture salaries do not cross the overflow check. |
| PASS | `parse_dk_csv` line 89 `or` to `and` | Empty body still raises `missing header` from the header read. |
| UNKNOWN | `parse_dk_csv` line 114 four `or` to `and` | Every fixture row has all five fields. A row missing one field is not asserted. |
| UNKNOWN | `parse_dk_csv` line 127 `False` to `True` | No blank Salary cell. The unmutated code rejects it as `invalid number`. |
| UNKNOWN | `_cell` line 142 `>=` to `>` | No short CSV row. |
| PASS | `opponent_abbr` lines 176 and 178 `and` to `or` | Fixture games have two different teams, so the opponent is unchanged. |
| PASS | `_load_slate_data` line 244 `or` to `and` | Every loaded `Game Info` is non-empty, so the stored text is unchanged. A blank Game Info is not asserted. |
| PASS | `_report` lines 270 and 272 `flush=True` to `False` | The line is still printed. |
| PASS | `_csv_member` lines 320–321 | The sample zip has one CSV, so the preferred-name check and the fallback pick the same file. |
| UNKNOWN | `fetch_staged_artifact` lines 340, 357, 361 | The fake downloader returns one zip for every URL, and the skip test clears both token and repo together. A single missing env var is not asserted. |
| PASS | `main` lines 397–399 `required=True` to `False` | Tests always pass `--csv`, `--season`, and `--week`. |
| UNKNOWN | `run_dk_slate` lines 384 and 386, `main` lines 408 and 411 | Week 10, week 11, week 19, and season 1800 are tested. The exact edges 1, 18, 1999, and 2100 are not. |

Uncovered (not executed), result UNKNOWN:

- `fetch_staged_artifact` lines 344, 360, 366, 370 and `main` lines 407, 417, 428. Coverage did not mark those sites hit. Non-integer season text, a missing `DATABASE_URL`, an empty artifact list, and a zip with no CSV are not in the suite.
- All 14 sites in `upgrade()` of `migrations/versions/0003_dk_classic_slate.py`. Coverage did not attribute that function. `tests/test_schema.py` still checks column types, both numeric scales, the primary key, the three indexes, and `ON DELETE RESTRICT`.

`loader/tables.py` `fields` had 2 sites, both killed.

## Decisions

- `TeamAbbrev` is stripped and uppercased, then must exist in `teams`. There is no extra alias table. The SPEC says the export codes are already nfl-like.
- `load_runs` has no week column, so the week is `week=<n>` in `notes`. `source_url` is `file:<filename>`. `source_version` is the sha256. One `load_runs` row per CLI invocation.
- Showdown rejection runs after the header and row checks and before any write. A bad header and a Showdown file both leave the previous slate in place.
- DST is `DST` in Position or Roster Position. It is not counted as unmapped skill.
- The scheduled job does not download a salary file from DraftKings. A missing staged file is a failed `dk_classic_slate` load.

## Not run

The GitHub Actions slate job was not started. This environment has no Neon `DATABASE_URL` and no staged production CSV. CI runs the pytest suite, not that workflow.
