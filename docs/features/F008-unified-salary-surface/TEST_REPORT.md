# F008 test report

Status: staged implementation evidence. Not release-ready. Blocked on merge of F005 PR 19, F006 PR 21, and F007 PR 22. No production migration, optimizer grant in production, live capture, or schedule activation. No season inventory was certified.

Branch: `cursor/f008-unified-salary-bb63`. Pull-request base: `cursor/f007-dknfl-historical-loader-bb63`. Migration chain: `0005` (F005 `f9f1dfb965406822b51c9a9100eca457829263c2`) → `0006` → `0007` → `0008`. `alembic heads` prints only `0008`. F005's Alembic head stays `0005`. The savepoint and `BudgetHTTPTransport` stay in the owner's commits.

## Design

Stored selection batches, not a live union and not a refresh service. A failed rebuild leaves the prior batch. `loader/salary_unified.py` copies F003 and F004 into adapter snapshots, writes interpretations and one batch, and migration `0008` creates `salary_private.dk_salary_unified`. Native IDs are not coalesced. DFF never becomes a ready pool. Archive modules are not imported.

One shared test adaptation was required because this branch owns the view name and the head revision: `tests/test_dk_lobby.py` keeps the real view when it is already present and only drops a stub it created, and `tests/test_dknfl_archive.py` compares the flag-on revision to `ScriptDirectory.get_current_head()`.

## Acceptance tests

Command: `DATABASE_URL=postgresql:///seam_f008 pytest tests/test_salary_unified.py -q` then the full suite below. All sixteen passed.

| AT | Result | Evidence |
|---|---|---|
| AT1 | PASS | `test_at1_view_columns_and_attribution`. Dictionary columns, lobby attribution, `dk_id` filled, `dff_player_id` null. No web route. |
| AT2 | PASS | `test_at2_different_games_do_not_merge`. Main and holiday revisions stay apart. Each selected pool is one snapshot. |
| AT3 | PASS | `test_at3_identity_namespaces`. A DFF id equal to a real GSIS stays unresolved and is not copied into `dk_id`. DST maps by team. A team mismatch stays unresolved. |
| AT4 | PASS | `test_at4_observation_order_and_ties`. Cutoff before the final A observation selects B. After that observation, A is selected again. Equal timestamps pick the higher artifact SHA. |
| AT5 | PASS | `test_at5_archive_chronology_needs_a_choice`. Two DKNFL SHAs without a choice select nothing and flag `chronology_unknown`. An explicit choice anchors the named snapshot, which is the earlier file. |
| AT6 | PASS | `test_at6_no_pool_filling`. An extra full-export player is `alternative_not_in_anchor`. Unresolved, subset, and rejected-row snapshots are not optimizer-ready. A ledger with no snapshot is not turned into a lobby snapshot. |
| AT7 | PASS | `test_at7_official_priority`. A later lobby effective time beats an earlier owner export. Equal effective time selects only the owner export. A different revision does not join that pool. |
| AT8 | PASS | `test_at8_disagreement_and_resolution`. Unresolved salary disagreement keeps alternatives and blocks ready. An anchor resolution stays flagged and becomes ready. A cross-source chosen ref stays blocked. |
| AT9 | PASS | `test_at9_unsafe_pool_flags`. Duplicate, zero salary, blank placeholder, and plausible reject are flagged. None are optimizer-ready. The blank row is counted. |
| AT10 | PASS | `test_at10_f003_stays_legacy`. The adapter row is `legacy_unknown`, not selected into the live slate. `dk_points` remain in the private row image. The public table is unchanged. |
| AT11 | PASS | `test_at11_f004_current_cohort_only`. Two current hashes become two adapter snapshots, `raw_retained` false, not ready. The public slate table is unchanged. |
| AT12 | PASS | `test_at12_reuse_then_new_evidence`. The same input reuses one batch and writes two succeeded audits. A new mapping version appends a batch and leaves the pinned batch queryable. |
| AT13 | PASS | `test_at13_failure_keeps_prior_batch`. Injected mid-batch and duplicate-key faults roll back. Two concurrent identical rebuilds leave one batch. Source rows stay put. |
| AT14 | PASS | `test_at14_coverage_denominators`. An empty rebuild stores a null skill rate. Public notes do not carry a 95% or 98% target. |
| AT15 | PASS | `test_at15_private_grants`. Web cannot read the view, DFF rows, or `dk_classic_slate`, and can read `teams`. Optimizer can select the view and cannot read DFF rows or insert a batch. Grants were applied twice. |
| AT16 | PASS | `test_at16_bounded_failures`. A missing snapshot id, a naive cutoff, and an oversized mapping fail. The prior batch remains. Stdout, stderr, and public notes omit the salary token and the local path. |

## Suite

`ruff check loader web tests migrations` passed.

`DATABASE_URL=postgresql:///seam_f008 pytest -q` with local trust authentication: `233 passed, 2 skipped`. `alembic heads` is `0008`.

`gitleaks detect --source . --redact --no-banner --no-git` reported `no leaks found`.

UncleBob Mutator `--changed`: UNKNOWN. `mutator` is not on `PATH` and `/agent/repos/crapper` is absent. It was not installed.

## Upstream archive evidence

The positive archive rerun is recorded on F007. Fresh isolated `seam_validate`, public nflverse `games.parquet` sha256 `0bc6e1221d68535848e58b37c3adf298907be2a3759f7d3abb986c7e7f8587e2` version `2026-11-06 20:46:43 EST`, teams sha256 `46955c6de3ff83e6ce229d278bc56a7772be287854f4b3a9666b151339568266` version `2026-03-27 11:49:45 EDT`. Empty games: `selected=62 succeeded=0 failed=62`. After that schedule load: `selected=62 succeeded=26 failed=36` (`game_evidence_missing=35`, `game_info_unparsed=1`), `rows_read=27788`, `rows_valid=27773`, `rows_rejected=15`, snapshots 26. Classifier counts: matched 26, `LAR`-token-only 34, other missing 1, unparsed 1. No alias was applied. DFF companion artifact id, kind, source, and body SHA-256 read back from the database: 80/80. Private HTML hashes are not listed.
