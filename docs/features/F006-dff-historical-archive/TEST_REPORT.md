# F006 test report

Status: implementation evidence for review. Not release-ready. Blocked on merge of F005 PR 19. No production migration, grant, capture, or schedule activation. No season inventory was certified.

Branch: `cursor/f006-dff-historical-loader-bb63`. Base: `cursor/f005-dk-lobby-capture-7241`. Migration `0006` revises `0005`.

## Design

Design A, one shared archive module imported by both loaders, was rejected because it would make F007 depend on F006. Design B is this PR: `loader/dff_archive.py` parses Daily Fantasy Fuel files and writes `salary_private.dff_salaries` plus the shared artifact, observation, snapshot, and ledger tables. It calls F005 only for hashes, the advisory lock, and storage guards. F005 insert and reconcile functions still hardcode `dk_lobby`, dataset `dk_lobby_salaries`, and parser `f005.1`, so this PR does not change those functions.

`loader/schedule_proof.py` is not called. No authority root was invented.

One F005 test assertion was adapted. `tests/test_dk_lobby.py` expected flag-on migrate to stop at revision `0005`. `loader/migrate.py` returns alembic `head` when `SALARY_PRIVATE_MIGRATION` is exactly `true`, and that head is now `0006` on this branch. The assertion follows the current head. Flag-off behavior is unchanged: a fresh database stops at `0003`, and a database already at `0005` stays at `0005` until the flag is exactly `true`.

## Acceptance tests

Command: `DATABASE_URL=postgresql:///seam_test pytest tests/test_dff_archive.py -q`

Result: `12 passed`.

| AT | Result | Evidence |
|---|---|---|
| AT1 | PASS | `test_at1_only_dff_rows_and_contracts`. Mixed manifest loads one DFF row. DKNFL file bytes are absent from artifacts. PK and both indexes exist. No `dk_id` or `gsis_id` column. F003, F004, and lobby counts stay unchanged. |
| AT2 | PASS | `test_at2_exact_bytes_order_and_blank_row`. BOM, CRLF, quoted name, extra column, and a blank row read back. Manifest and gzip bytes match. `duration_ms`, `fetched_at`, and `source_published_at` are null. |
| AT3 | PASS | `test_at3_january_season_comes_from_manifest_not_path`. Path label `2026-mislabeled.csv` stores season 2025 week 18. |
| AT4 | PASS | `test_at4_file_failures_keep_evidence_and_prior_success`. Hash, count, core header, column set, row date, row week, missing companion, zero valid rows, non-CSV, and a contradicting game each fail with no snapshot. The earlier good snapshot remains. The mismatched file's bytes are retained. |
| AT5 | PASS | `test_at5_rejected_salary_stays_non_ready_subset`. Invalid salary is a rejected row with null salary and raw token `nope`. Snapshot exists, `source_pool_kind=subset`, `optimizer_ready=false`, `draft_group_id` null. No lobby rows. |
| AT6 | PASS | `test_at6_christmas_subset_keeps_duplicates_and_skips_saturday`. Three Sunday games are stored. The Saturday game id is absent. Duplicate vendor rows and the salary conflict flag are both kept. |
| AT7 | PASS | `test_at7_rerun_reuses_and_correction_appends`. Second identical run adds an observation and no salary row. A corrected file appends a snapshot and leaves the original `5000` row. The same bytes under a second path reuse the CSV artifact. |
| AT8 | PASS | `test_at8_neighbor_files_commit_when_middle_publish_rolls_back`. Files a and c commit. File b rolls back its snapshot, keeps its ledger row, and the invocation exits 1. |
| AT9 | PASS | `test_at9_reconcile_after_commit_and_unreachable_database`. After a commit and before public audit finalization, reconcile marks the run succeeded without adding salary rows. A second run does not duplicate them. `postgresql://seam@127.0.0.1:1/none` exits 1 with stderr `database_unreachable`. |
| AT10 | PASS | `test_at10_manifest_and_path_boundaries`. Missing manifest, conflicting duplicate path, escaping symlink, `../` traversal, and an absolute path fail before the outside file is stored. `urlopen` is patched to raise and is not required. |
| AT11 | PASS | `test_at11_grants_guards_and_gate`. An oversized object does not publish or evict the prior snapshot. Web role can read `dk_classic_salaries` and cannot read `dff_salaries`, artifacts, or `dk_classic_slate` after two grant passes. Flag-off migrate on a database at `0005` does not create `dff_salaries`. Flag-on migrate creates it at revision `0006` and a later flag-off call stays there. |
| AT12 | PASS | `test_at12_logs_attribution_and_scanner`. Stdout contains only the DFF attribution sentence among source credits. Salary token and private path token are absent from stdout, stderr, and public `load_runs` notes. No DFF cron workflow and no web route. `gitleaks detect --no-git` exit 0. |

## Suite

`ruff check loader web tests migrations` passed.

After merging PR 19 head `4d85d8c`, `DATABASE_URL=postgresql:///seam_test pytest -q` with local trust authentication (the CI setting) reported `198 passed, 2 skipped`. On this VM's default peer authentication, `tests/test_readonly.py::test_at18_read_only_role` returns 503 because the login role fails peer auth. That test passed under trust, and peer authentication was restored. It is not an F006 assertion.

`gitleaks detect --source . --redact --no-banner --no-git` reported `no leaks found`.

UncleBob Mutator `--changed`: UNKNOWN. `mutator` is not on `PATH` and `/agent/repos/crapper` is absent. It was not installed.

## Offline archive load

Isolated database `seam_evidence`, migrated with alembic to head (`0006`). No games rows were loaded, and `DK_SCHEDULE_AUTHORITY_SHA256` was unset. Command:

`python -m loader.dff_archive --archive-root /tmp/dk-historical-gap --manifest /tmp/dk-historical-gap/MANIFEST.csv --trigger local`

Stdout:

```
attribution=Salary/projection subset via Daily Fantasy Fuel (dailyfantasyfuel.com). Not affiliated with DraftKings.
selected=80 succeeded=80 failed=0 reused=0 not_selected=62 rows_read=17026 rows_valid=17026 rows_rejected=0
```

Exit 0. Aggregates from that database:

| Check | Value |
|---|---|
| Snapshots | 80 |
| `dff_salaries` rows | 17026 |
| Valid / rejected | 17026 / 0 |
| `draft_group_id` null | 80 |
| `source_pool_kind=subset` | 80 |
| `optimizer_ready=true` | 0 |
| Lobby salary rows | 0 |
| Artifacts with source `dknfl` | 0 |
| DFF observations | 80 |
| Succeeded / failed load runs | 80 / 0 |
| DFF CSV artifacts / bytes | 80 / 1888193 |
| DFF gzip artifacts / bytes | 80 / 6680352 |
| Control artifacts | 1 CSV (698 bytes) and 2 manifest-kind documents (87126 bytes) |
| Artifact whose size equals `SALARY_OBSERVATIONS.csv` | 0 |
| Snapshot seasons | 2022–2025 × 18 and 2026 × 8 |

The 18 `evidence/dff-2021-week*.html.gz` files were not selected and were not stored. This load does not certify a season, a complete player pool, or optimizer readiness. Successful parsing of a subset is not a usable F005 snapshot.
