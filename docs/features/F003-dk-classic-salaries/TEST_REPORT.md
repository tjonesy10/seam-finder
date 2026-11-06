# F003 test report

Date: 2026-11-06. Scope: `dk_classic_salaries` migration, RotoGuru SCSV loader, `workflow_dispatch` workflow, AT1–AT15, and the blank DK salary regression. No read API and no browse page.

## Results

| AT | Result | Evidence |
|---|---|---|
| AT1 | PASS | `tests/test_dk_classic.py::test_at1_parse_2015_week_1_fixture`. Fixture `tests/fixtures/rotoguru/2015/week_01.scsv`: Brady GID 1131 is 27.62 / 7700; Carolina Defense GID 7005 is `Def` / 21 / 3100. |
| AT2 | PASS | `test_at2_dst_maps_to_team_and_null_gsis`. Carolina Defense → `team_abbr=CAR`, `gsis_id` null, `opponent_abbr=JAX`, `game_id=2015_01_CAR_JAX`. |
| AT3 | PASS | `test_at3_brady_maps_to_the_week_stat_not_latest_team`. Tom Brady maps to `00-0019596` from the NE week-1 stat, not the other Tom Brady whose `latest_team` is NE. |
| AT4 | PASS | `test_at4_second_load_is_idempotent_and_deletes_nothing`. Second run `rows_deleted=0`. Row equality ignores `loaded_at` and `source_fetched_at`. |
| AT5 | PASS | `test_at5_removed_gid_is_deleted_and_other_weeks_stay`. Dropping GID 9001 deletes that row (`rows_deleted=1`) and leaves week 2. |
| AT6 | PASS | `test_at6_bad_header_keeps_rows_and_exits_1`. `python -m loader.dk_classic` returns 1, `load_runs.status=failed`, prior rows unchanged. |
| AT7 | PASS | `test_at7_load_runs_record_week_trigger_and_unmapped_skill`. Dataset `dk_classic_salaries`, season, trigger, `source_url`, and counts are set. Notes are `week=1; unmapped_skill=1`. |
| AT8 | PASS | `test_at8_recorded_sample_matches_at_least_98_percent`. 49/50 non-Def rows with `dk_salary>0` have `gsis_id` (98%). The unmatched skill row stays null. DST is not in the denominator. |
| AT9 | PASS | `test_at9_no_nfldfs_or_draftkings_in_production_code`. `pyproject.toml`, `loader`, `web`, `migrations`, and workflows have no `nfldfs` import and no `draftkings.com`. |
| AT10 | PASS | `test_at10_workflow_does_not_print_secrets` and `tests/test_refresh.py::test_at26_no_secrets_in_repo` (gitleaks v8.30.1, no passworded database URL). |
| AT11 | PASS | `test_at11_backfill_requests_only_reg_weeks_and_skips_missing`. Seasons 2015–2021 request weeks 1–18 only (126 calls). Missing weeks are `succeeded` with `rows_skipped=1` and no salary rows. `parse_weeks("19")` raises. Header-only input does not delete existing rows (`test_missing_header_only_week_does_not_delete_existing_rows`). |
| AT12 | PASS | `test_at12_zero_salary_is_loaded`. GID 9001 stored with `dk_salary=0`. |
| AT13 | PASS | `test_at13_attribution_constant_is_exact`. `web.attribution.ROTOGURU_DK_CLASSIC_ATTRIBUTION` is the exact Cosmo line. |
| AT14 | PASS | `test_at14_unmapped_team_keeps_previous_rows`. Team code `zzz` fails the week, `load_runs.status=failed`, previous rows unchanged. |
| AT15 | PASS | `test_at15_workflow_is_dispatch_only`. `.github/workflows/dk-classic-salaries.yml` has `workflow_dispatch` and no `schedule` or `cron`. |
| Blank DK salary | PASS | `tests/test_dk_classic.py::test_blank_dk_salary_is_loaded_as_zero`. Fixture `tests/fixtures/rotoguru/2015/week_06_blank_salary.scsv` is the live 2015 week 6 line `6;2015;5295;Grant, Ryan;WR;was;a;nyj;4.2;`. Parse and load store GID 5295 with `dk_points=4.2` and `dk_salary=0` (`team_abbr=WAS`, `opponent_abbr=NYJ`), and the week succeeds. A non-numeric salary still raises `invalid scsv integer: DK salary`. |

## Commands

```text
ruff check loader web tests migrations
All checks passed!

pytest -q
117 passed, 2 skipped, 1 warning in 6.73s
```

The earlier forge run, before the blank-salary test, was `116 passed, 2 skipped, 1 warning in 7.08s`. The extra pass is `test_blank_dk_salary_is_loaded_as_zero`.

The skips are the nflverse network test and `test_live_2015_week_1_scsv_contains_brady_and_carolina` unless `RUN_NETWORK_TESTS=1`. With that set, the live test passed (`1 passed in 0.49s`): the public 2015 week 1 body parses Brady 27.62/7700 and Carolina Defense 21/3100.

## Loader proof (local Postgres)

Teams came from the committed nflverse fixture. Salaries came from the committed SCSV. `gsis_id` is null here because that fixture has no 2015 `player_week_stats`; AT3 covers the match when those rows exist.

```text
$ python -m alembic upgrade head
$ python -m loader --datasets teams --seasons 2015 --trigger local
teams season=- status=succeeded
$ python -m loader.dk_classic --seasons 2015 --weeks 1 --trigger local
dk_classic_salaries season=2015 week=1 status=succeeded

 rotoguru_gid |     name_raw     | pos_raw | team_abbr | opponent_abbr | dk_points | dk_salary | gsis_null
         1131 | Brady, Tom       | QB      | NE        | PIT           |     27.62 |      7700 | t
         7005 | Carolina Defense | Def     | CAR       | JAX           |     21.00 |      3100 | t
         9001 | Fictional, Zero  | WR      | NE        | PIT           |      0.00 |         0 | t

 status    | rows_read | rows_upserted | rows_deleted | rows_skipped | notes
 succeeded |         3 |             3 |            0 |            0 | week=1; unmapped_skill=2
```

## Mutation testing

Tool: [unclebob/mutator](https://github.com/unclebob/mutator) with [unclebob/crapper](https://github.com/unclebob/crapper) checked out beside it. Command: `mutator --max-workers 1 --test-command "python3 -m pytest -q"` on `loader/dk_classic.py`, `loader/tables.py`, `web/attribution.py`, and `migrations/versions/0002_dk_classic_salaries.py`. One worker, because the suite shares one Postgres.

| File | Killed | Survived | Uncovered | Sites |
|---|---:|---:|---:|---:|
| `loader/dk_classic.py` | 98 | 9 | 4 | 111 |
| `loader/tables.py` | 2 | 0 | 0 | 2 |
| `web/attribution.py` | 0 | 0 | 0 | 0 |
| `migrations/versions/0002_dk_classic_salaries.py` | 0 | 0 | 16 | 16 |
| Total | 100 | 9 | 20 | 129 |

Score on executed mutants: 100/109 (91.7%). `dk_classic.py` alone, after the extra tests: 98/107 (91.6%).

Survivors, left in place because they do not change a result the tests can see:

- `gsis_for`: `len(hits) > 1` to `>=` or `> 0`. The `len == 1` branch already returned.
- `_points`: three `0` to `1` edits in the integer-digit count. None of them crosses the `> 6` overflow check for 0 or for `999999.99`.
- `_player_indexes`: `week is not None and stat_team` to `or`. The query returns both or neither.
- `_report`: `flush=True` to `False`. The line is still printed.
- `run_dk_classic`: `pool_pre_ping=True` to `False`.

The 16 migration mutants were not run. Coverage did not attribute `upgrade()`. `tests/test_schema.py` still checks the column types, the numeric(8,2) scale, the primary key, the three indexes, and `ON DELETE RESTRICT`.

## Decisions

- `loaded_at` is on `dk_classic_salaries`. The SPEC schema and AT4 name it. The data-dictionary draft on PR #10 omitted it.
- `load_runs` has no `week` column in that data dictionary, so the week is recorded as `week=<n>` in `notes` and in `source_url`. One `load_runs` row per season and week.
- The live URL returns HTML. The SCSV header is on the same line as `<pre>`. The parser starts at that header. A committed fixture may be raw SCSV.
- A header with no data rows is a missing week (2015 week 18 is that shape). It is skipped. It does not delete rows already stored for that week. An empty body is the same. A non-empty body with no header fails the week.
- `oak` maps to `OAK` through 2019 and to `LV` from 2020. RotoGuru still writes `Oppt=oak` for the Raiders in 2021 while `Team=lvr`.
- Opponent `-` is not in the team map, so that week fails (Q4). Live weeks: 2016 week 5 (1 of 356 rows), 2017 week 11 (26 of 380), 2020 week 5 (1 of 374), 2020 week 7 (1 of 377). A mapped code whose `team_abbr` is missing from `teams` also fails that week (`unresolved team_abbr`).
- A blank `DK salary` (the field is present and empty, as in a trailing `;`) loads as `0` (Q7). Production run [42274838604](https://github.com/tjonesy10/seam-finder/actions/runs/42274838604) failed those weeks with `invalid scsv integer: DK salary`. A 2015–2021 SCSV scan on 2026-11-06 found only empty salary fields for that error (for example 2015 week 6 GID 5295 `Grant, Ryan`). A non-numeric salary still fails the week. Weeks whose only problem is `Oppt=-` are unchanged. 2017 week 11 has both a blank salary and `Oppt=-`, so that week still fails on the unmapped team code after this fix.
- Skill match prefers the `player_week_stats` row for that team-week (name and position). An ambiguous set stays null. An empty set uses the one player with that name and position tied to the team by `latest_team` or any REG stat that season. DST is not an unmapped skill.

## Not run

The GitHub `workflow_dispatch` job was not started. This environment has no Neon `DATABASE_URL`. CI runs the pytest suite, not that workflow.
