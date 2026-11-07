# F008 test report

Status: staged implementation evidence. Not release-ready. Blocked on merge of F005 PR 19, F006 PR 21, and F007 PR 22. No production migration, optimizer grant in production, live capture, or schedule activation. No season inventory was certified.

Branch: `cursor/f008-unified-salary-bb63`. Pull-request base: `cursor/f007-dknfl-historical-loader-bb63`. Migration chain: `0005` (F005 `206edf7e0e739b451e7b3d12501cdb2e0357a1b3`) → `0006` → `0007` → `0008`. `alembic heads` prints only `0008`. F005's Alembic head stays `0005`. The savepoint, `BudgetHTTPTransport`, and the httpcore-to-httpx body-error translation stay in the owner's commits. Main docs `b15ab560` arrived through that F005 merge.

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

`DATABASE_URL=postgresql:///seam_f008 pytest -q` with local trust authentication, after merging F005 `206edf7`: `235 passed, 2 skipped`. `alembic heads` is `0008`.

`gitleaks detect --source . --redact --no-banner --no-git` reported `no leaks found`.

UncleBob Mutator `--changed`: UNKNOWN. `mutator` is not on `PATH` and `/agent/repos/crapper` is absent. It was not installed.

## Upstream archive evidence

The positive archive rerun is recorded on F007. Fresh isolated `seam_validate`, public nflverse `games.parquet` sha256 `0bc6e1221d68535848e58b37c3adf298907be2a3759f7d3abb986c7e7f8587e2` version `2026-11-06 20:46:43 EST`, teams sha256 `46955c6de3ff83e6ce229d278bc56a7772be287854f4b3a9666b151339568266` version `2026-03-27 11:49:45 EDT`. Empty games: `selected=62 succeeded=0 failed=62`. After that schedule load: `selected=62 succeeded=26 failed=36` (`game_evidence_missing=35`, `game_info_unparsed=1`), `rows_read=27788`, `rows_valid=27773`, `rows_rejected=15`, snapshots 26. Classifier counts: matched 26, `LAR`-token-only 34, other missing 1, unparsed 1. No alias was applied. DFF companion artifact id, kind, source, and body SHA-256 read back from the database: 80/80. Private HTML hashes are not listed.

## Gate corrections

The earlier AT1–AT16 table did not cover the gaps below. Those rows stay historical. The new tests are the evidence for these corrections. AT10 and AT15 were not part of this gate and still pass inside the suite.

| Finding | Before | After |
|---|---|---|
| Unknown rules, naive kickoff, game/team/season mismatch, unknown draft group bridging two known groups | A self-hash plus `complete_pool` and a null group could verify and connect group A to group B | `test_slate_rules_kickoff_game_and_group_bridge`: none of those four publishes an optimizer-ready row |
| Newer incomplete snapshot resurrects an older ready one; duplicate native IDs can be mapped ready | Latest was chosen only among already-complete snapshots | `test_newer_incomplete_blocks_older_ready`: the older snapshot is not selected, and duplicate `dk_id` rows are not optimizer-ready |
| One anchor resolution clears every dispute | A single `chosen_ref` on the anchor set `resolved` for the pool | `test_one_resolution_does_not_clear_every_dispute`: two disagreed entities with one resolution stay not optimizer-ready |
| Publish used a different lock from capture, reset the invocation budget per artifact, and took `committed_at` before the lock | Concurrent identical rebuilds could collide, and a source writer was not on the same lock | Session lock `582005` is taken before the repeatable-read snapshot. `test_rebuild_waits_for_the_source_writer_lock`: `committed_at` is not earlier than the writer's release. Invocation bytes accumulate across artifacts in one rebuild |
| Coverage was one global rate and counted ready rows, including DST, as mapped skill | Empty AT14 only | `test_coverage_counts_skill_apart_from_dst`: source bucket skill 2, DST 1, mapped skill 1, unmapped 1, rate `1/2` |
| A missing source table was `database_unreachable` and a committed batch could leave the audit running | The run row stayed `running` | `test_missing_table_fails_closed_and_audit_can_reconcile`: the missing-table run is `failed` with `source_table_missing`. `fault=after_commit` leaves the batch, and `reconcile` marks that run `succeeded` |
| `0008` tables had no `loaded_at` and no lowercase SHA checks | Columns and checks were absent | The same test reads `loaded_at` NOT NULL on all three tables and the three SHA check constraints |

`DATABASE_URL=postgresql:///seam_f008 pytest -q` with trust authentication after these corrections: `243 passed, 2 skipped`. `alembic heads` is `0008`. `ruff check loader web tests migrations` passed. This suite does not certify the 26-of-62 DKNFL archive load, and it does not add a `LAR` alias.

## Second gate, remaining items

The items the reviewer closed (per-entity resolution, superseded alternatives, lock-before-snapshot, serialized timestamp, fingerprint, `loaded_at`/hash checks, missing-table audit, and a direct `reconcile` call) were not reworked.

On `68a33f4` the five new tests failed:

| Test | Red result |
|---|---|
| `test_mapping_must_match_retained_context` | A DFF source label on a lobby snapshot published `ready=1` |
| `test_unclaimed_newer_group_and_stale_f004_and_blank_reject` | The older claimed snapshot stayed selected, and the blank-rejected DKNFL file was `ready=1` |
| `test_reused_artifacts_count_toward_invocation_budget` | The second rebuild of already-stored artifacts exited 0 under a limit smaller than their sum |
| `test_mixed_source_coverage_reconciles` | The DFF DST row was counted as skill (`skill == 2`) |
| `test_reachable_sql_failure_and_entrypoint_reconcile` | A statement timeout left the run `running` and printed `database_unreachable` |

After the retained-context checks, those five tests pass. A supplied source or evidence artifact that does not match the stored snapshot is `bad_mapping_reference`. A claim cannot replace a known draft group. A rehashed kickoff does not agree with the stored game id and kickoff. An RB row cannot become `dst:`. A newer successful snapshot of the same native group blocks an older ready one even when the newer snapshot has no mapping claim. An F004 snapshot is current only when its row image matches the rows that still carry that hash. Any rejected DFF or DKNFL row, including a blank one, blocks readiness. Reused artifact bytes are checked against the invocation total before the stored row is reused. DFF `position_raw` is the roster token used for skill versus DST. `slate_verified` follows the interpretation status. Coverage now includes `dst_unresolved`, `excluded_duplicates`, and `ready_pools`, and the mixed DFF/legacy/unresolved fixture reconciles to `raw_records`. Reachable `OperationalError` finalizes the run as `statement_timeout`. The next `main` invocation reconciles a batch whose public audit did not finish.

`DATABASE_URL=postgresql:///seam_f008 pytest -q` with trust authentication on this head: `249 passed, 2 skipped`. `alembic heads` is `0008`. Mutator remains UNKNOWN. The 26-of-62 DKNFL load is still not a certified season.

## Third gate, four mechanisms

On `8d734f14` these four tests failed:

| Test | Red result |
|---|---|
| `test_latest_complete_history_and_separate_null_groups` | Complete A, incomplete B, complete C selected nothing (`ready=0`). A null-group week did not stay selectable beside a later unrelated null-group file |
| `test_null_kickoff_can_be_enriched_without_becoming_ready` | A stored `kickoff_at` of null left the interpretation `unresolved` when the claim added an explicit kickoff |
| `test_reconcile_waits_for_the_active_attempt` | The second invocation marked the locked, not-yet-committed run `failed` while that attempt still held the capture lock |
| `test_stale_f004_quality_cannot_stay_ready` | After a second hash was added, the old single-hash snapshot stayed `optimizer_ready` when the new adapter observation was after the cutoff |

History is now one native draft group, or one snapshot when the group is null. The latest complete snapshot in that history can anchor; an older incomplete file does not block a later complete one, and a null group is not shared across unrelated archives. A known kickoff still contradicts a different claim. A null kickoff can be filled by a reviewed offset and the interpretation can be verified, while a DFF subset stays not optimizer-ready. Reconcile runs only after the capture lock is held, so a second invocation waits and does not finalize the active attempt early. An F004 snapshot matches the current cohort only when the row image and `mixed_hash_cohort` both match. The old single-hash snapshot is not ready once a second hash exists and the new adapter observation is after the cutoff.

`DATABASE_URL=postgresql:///seam_f008 pytest -q` with trust authentication after this correction: `253 passed, 2 skipped`. `alembic heads` is `0008`. Previously closed checks were not reopened. Mutator remains UNKNOWN.

## Known whole-slate membership

On `19ffaede`, `test_known_lobby_set_rejects_an_extra_claimed_game` was red. A lobby snapshot storing games A and B, with kickoffs, was verified and `ready=2` when the claim recomputed its hash over A, B, and an extra game and set `complete_pool` true.

A retained set whose matchups and kickoffs are already known now requires the same membership. Extra claimed games are a conflict, so that slate is not verified and not optimizer-ready. A DFF snapshot whose kickoff is null can still receive a reviewed offset on the same opponents and game id: the interpretation stays `verified`, and the row stays `subset` and not optimizer-ready. A known kickoff that disagrees with the claim is still rejected.

`DATABASE_URL=postgresql:///seam_f008 pytest -q` with trust authentication: `254 passed, 2 skipped`. `alembic heads` is `0008`. Mutator remains UNKNOWN.

## Membership scope is not kickoff population

The section above treated a fully populated matchup and kickoff list as a closed slate. That premise is false. Timing completeness and membership scope are independent, and `source_pool_kind=full_export` only names the export format. F007 states that explicitly. The retained signal is `game_set_sha256`: the dictionary fills it only when the game set is verified. F005 writes it for the captured draft-group list. F006 and F007 insert null, so their stored games stay observed facts.

On `1932401` the two crossed cases were red:

| Test | Red result |
|---|---|
| `test_verified_game_set_with_unknown_kickoff_keeps_its_membership` | Lobby games A/B with `game_set_sha256` set and one `kickoff_at` null. The same two games with a reviewed kickoff were ready. Adding game C, recomputing the hash, and setting `complete_pool` true still published `verified` and `ready=2`. |
| `test_observed_subset_with_known_kickoffs_can_name_a_larger_slate` | DFF games A/B with both kickoffs filled and no `game_set_sha256`. A reviewed claim of A/B/C left the interpretation `unresolved` and selected nothing. |

Both are green after the check uses `game_set_sha256` and stops reading kickoff population as membership. The same-membership kickoff fill stays `verified`, `full_export`, and optimizer-ready. The extra game on that verified set is not `verified` and not ready. The observed subset may be a `verified` interpretation of the larger slate and stays `subset` and not optimizer-ready. `test_known_lobby_set_rejects_an_extra_claimed_game` still rejects fully populated lobby A/B plus game C, now because that fixture records `game_set_sha256`. Null-kickoff DFF enrichment and a contradictory known kickoff stay as they were.

`DATABASE_URL=postgresql:///seam_f008 pytest -q` with trust authentication: `256 passed, 2 skipped`. `alembic heads` is `0008`. Previously closed checks were not reopened. Mutator remains UNKNOWN.
