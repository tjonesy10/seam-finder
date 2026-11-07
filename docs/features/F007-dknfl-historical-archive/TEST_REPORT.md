# F007 test report

Status: implementation evidence for review. Not release-ready. Blocked on merge of F005 PR 19. No production migration, grant, capture, or schedule activation. No season inventory was certified.

Branch: `cursor/f007-dknfl-historical-loader-bb63`. Base: `cursor/f005-dk-lobby-capture-7241` at `1faaee6ee0664b671f63859f5c3ccd7d3c7c2d8a`. Migration `0007` revises `0005`. F006's `0006` is not on this branch. Merging both archive branches onto one line leaves two Alembic heads until a later down-revision stitch.

## Design

F007 does not import F006. `loader/dknfl_archive.py` parses original DraftKings CSV bytes and writes `salary_private.dknfl_salaries` plus the shared artifact, observation, snapshot, and ledger tables. DK `ID` stays `dk_id` on that table only. `source_pool_kind` is `full_export`, which records the export format and does not verify a complete main slate. `draft_group_id`, roster slots, and salary cap stay null. `optimizer_ready` stays false.

Corrected season, season type, and week are taken from matched `public.games` rows. A missing, ambiguous, or disagreeing game rejects the snapshot and keeps the artifact and ledger. This loader does not call `project_raw_season`, `repeatable_read`, or any other schedule-proof writer, and it does not invent an authority document.

F005-owned files are unchanged on this branch. `tests/test_dk_lobby.py` still expects a flag-on migrate to land on revision `0005`. With `0007` present, that assertion fails. The same assertion already follows alembic head on the F006 branch. It was not copied here.

## Acceptance tests

Command: `DATABASE_URL=postgresql:///seam_f007 pytest tests/test_dknfl_archive.py -q`

Result: `12 passed`. `seam_f007` is a separate local database. `seam_test` was left at the F006 revision and was not reused.

| AT | Result | Evidence |
|---|---|---|
| AT1 | PASS | `test_at1_only_dknfl_rows_and_contracts`. Mixed manifest loads two DKNFL rows. The other source file is not stored. PK and both indexes exist. No `dff_player_id` or `gsis_id`. F003 count and lobby rows stay unchanged. |
| AT2 | PASS | `test_at2_exact_bytes_and_duplicate_paths_share_bytes_only`. Two paths with the same BOM/CRLF bytes share one CSV artifact and keep two snapshot keys. Upstream commit `abc1234abc` and repository path are on the private observation. `duration_ms`, `fetched_at`, and `source_published_at` are null. |
| AT3 | PASS | `test_at3_blank_placeholders_stay_rejected`. Fifteen blank rows stay rejected with null salary and null `dk_id`. Two valid salaries match. No zero salary is created. |
| AT4 | PASS | `test_at4_corrected_weeks_keep_original_paths`. Mislabeled `2022/Week2/...` stores 2021 week 2. `2023/WEEK11_5/...` stores week 12 and only the Thanksgiving game ids. `2024/WEEK16/...christmas` stores week 17 and does not include the Saturday game. Original paths remain. |
| AT5 | PASS | `test_at5_two_game_and_post_keep_unknown_rules`. Monday two-game file stays REG. Postseason file stays POST. `draft_group_id`, roster slots, and salary cap are null. `full_export` and `optimizer_ready=false`. |
| AT6 | PASS | `test_at6_showdown_header_and_game_failures_keep_prior`. CPT, one game, missing salary column, manifest week disagreeing with matched games, and unmapped games each fail with no snapshot. Showdown ledger rows remain. The earlier good snapshot's row count is unchanged. |
| AT7 | PASS | `test_at7_duplicate_ids_remain_non_ready`. Conflicting duplicate `dk_id` rows are both kept and flagged. The snapshot exists and is not optimizer-ready. No lobby rows. |
| AT8 | PASS | `test_at8_rerun_reuses_and_correction_appends`. A second identical run adds an observation and no snapshot. Corrected bytes append a snapshot and leave the original salary row. |
| AT9 | PASS | `test_at9_neighbors_and_reconcile`. Weeks 1 and 3 commit when week 2's normalized write is rolled back. A commit before public audit finalization reconciles without new salary rows. An unreachable database exits 1 with stderr `database_unreachable`. |
| AT10 | PASS | `test_at10_boundaries_and_budget`. Missing manifest, conflicting path, escaping symlink, traversal, hash mismatch, and an oversized body fail closed. Outside bytes are not stored. Prior snapshots are not evicted. |
| AT11 | PASS | `test_at11_grants_leave_other_sources`. Web role can read `dk_classic_salaries` and `teams` and cannot read `dknfl_salaries`, artifacts, or `dk_classic_slate` after two grant passes. Flag-off at revision `0005` does not create `dknfl_salaries`. Flag-on creates it at revision `0007`. |
| AT12 | PASS | `test_at12_attribution_and_scanner`. Stdout uses the DKNFL credit. Salary token and private path token are absent from stdout, stderr, and public notes. No cron workflow and no web route. `gitleaks detect --no-git` exit 0. |

## Suite

`ruff check loader web tests migrations` passed.

`DATABASE_URL=postgresql:///seam_f007 pytest -q` with local trust authentication: `197 passed, 2 skipped, 1 failed`.

The failure is `tests/test_dk_lobby.py::test_production_migrate_stops_before_0004`: flag-on migrate reached revision `0007`, and the unchanged F005 test expects `0005`. Flag-off behavior is still `0003` for a fresh database and `0005` for a database already at `0005`. This branch does not edit that test.

`gitleaks detect --source . --redact --no-banner --no-git` reported `no leaks found`.

UncleBob Mutator `--changed`: UNKNOWN. `mutator` is not on `PATH` and `/agent/repos/crapper` is absent. It was not installed.

## Offline archive load

Isolated database `seam_dknfl`, migrated to head (`0007`). `public.games` was empty. `DK_SCHEDULE_AUTHORITY_SHA256` was unset. No schedule was invented.

Command: `python -m loader.dknfl_archive --archive-root /tmp/dk-historical-gap --manifest /tmp/dk-historical-gap/MANIFEST.csv --trigger local`

Stdout and stderr:

```
failed_reasons=game_evidence_missing:61,game_info_unparsed:1
attribution=Archived DraftKings salary export via pureslurp/DKNFL (GitHub). Not affiliated with DraftKings.
selected=62 succeeded=0 failed=62 reused=0 not_selected=80 rows_read=27788 rows_valid=27773 rows_rejected=15
```

Exit 1. Aggregates:

| Check | Value |
|---|---|
| Snapshots | 0 |
| `dknfl_salaries` rows | 0 |
| Ledger rows | 27788 |
| DKNFL observations with null snapshot | 62 |
| Load runs `game_evidence_missing` | 61 |
| Load runs `game_info_unparsed` | 1 |
| DKNFL CSV artifacts / bytes | 62 / 2819068 |
| Control artifacts | 1 CSV (698 bytes) and 2 manifest-kind documents (87126 bytes) |
| Lobby rows | 0 |

Sixty-one files failed because no loaded game matched their Game Info. One file failed because a non-placeholder Game Info value did not parse. Raw CSV bytes and every parseable ledger row were kept. No snapshot was published. This is not a certified season and not an optimizer-ready pool. The local nflverse fixture has 7 games and was not used as a stand-in for 2021–2024.
