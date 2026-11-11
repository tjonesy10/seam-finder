# F007 test report

Status: implementation evidence for review. Not release-ready. Blocked on merge of F005 PR 19. No production migration, grant, capture, or schedule activation. No season inventory was certified.

Branch: `cursor/f007-dknfl-historical-loader-bb63`. Pull-request base: `cursor/f006-dff-historical-loader-bb63`. F005 PR 19 head merged underneath is `206edf7e0e739b451e7b3d12501cdb2e0357a1b3`. Migration chain on this branch is `0005` → `0006` → `0007`. Alembic head of F005 stays `0005`. `alembic heads` prints only `0007`. The loaders do not import each other; the dependency is the revision line. The savepoint and `BudgetHTTPTransport` stay in the owner's commits.

## Design

F007 does not import F006. `loader/dknfl_archive.py` parses original DraftKings CSV bytes and writes `salary_private.dknfl_salaries` plus the shared artifact, observation, snapshot, and ledger tables. DK `ID` stays `dk_id` on that table only. `source_pool_kind` is `full_export`, which records the export format and does not verify a complete main slate. `draft_group_id`, roster slots, and salary cap stay null. `optimizer_ready` stays false.

Corrected season, season type, and week are taken from matched `public.games` rows. A missing, ambiguous, or disagreeing game rejects the snapshot and keeps the artifact and ledger. This loader does not call `project_raw_season`, `repeatable_read`, or any other schedule-proof writer, and it does not invent an authority document.

F005 runtime files are unchanged. The flag-on assertion in `tests/test_dk_lobby.py` is the copy already on the F006 branch: it follows the current Alembic head. `tests/test_dff_archive.py` uses that same head check on this branch so revision `0007` is not reported as a missing `0006`.

## Acceptance tests

Command: `DATABASE_URL=postgresql:///seam_f007 pytest tests/test_dknfl_archive.py -q`

Those tests, including `test_empty_games_fail_closed`, passed inside the stacked `211 passed` run below.

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

`DATABASE_URL=postgresql:///seam_linear pytest -q` with local trust authentication, after F006 was merged and `0007` revised `0006`: `211 passed, 2 skipped`. `alembic heads` is `0007`.

Flag-on migrate follows the current Alembic head in both `tests/test_dk_lobby.py` (brought by the F006 merge) and `tests/test_dff_archive.py` (updated on this branch so a later revision is not mistaken for a missing `0006`). Flag-off behavior is still `0003` for a fresh database and `0005` for a database already at `0005`.

`gitleaks detect --source . --redact --no-banner --no-git` reported `no leaks found`.

UncleBob Mutator `--changed`: UNKNOWN. `mutator` is not on `PATH` and `/agent/repos/crapper` is absent. It was not installed.

## Offline archive load

### Negative: empty games

`test_empty_games_fail_closed` keeps this case in the suite. A two-game file with `games` empty exits 1, reason `game_evidence_missing`, snapshot null, ledger rows kept, and no `dknfl_salaries` rows.

An earlier isolated database with no games at all returned `selected=62 succeeded=0 failed=62` (`game_evidence_missing=61`, `game_info_unparsed=1`), snapshots 0, ledger 27788. That run is not a successful load.

### Positive: independent nflverse schedule

No schedule file was attached to the archive. The repository fixture has 7 games, which cannot cover 2021–2024. The public nflverse schedules release was read once with the existing release URL. Downloads that return 401, 403, or 429 were not retried. Bytes were staged outside the repo.

| Object | SHA-256 | Publisher version |
|---|---|---|
| `schedules/games.parquet` (523439 bytes) | `0bc6e1221d68535848e58b37c3adf298907be2a3759f7d3abb986c7e7f8587e2` | `2026-11-06 20:46:43 EST` |
| `teams/teams_colors_logos.parquet` (13361 bytes) | `46955c6de3ff83e6ce229d278bc56a7772be287854f4b3a9666b151339568266` | `2026-03-27 11:49:45 EDT` |

Teams and games for 2021–2026 were loaded only by `loader.run` from that local mirror into database `seam_archive` after migrations through `0007`. Game rows were not built from salary Game Info. `DK_SCHEDULE_AUTHORITY_SHA256` was unset. This is not an F005 schedule-authority certificate.

Command: `python -m loader.dknfl_archive --archive-root /tmp/dk-historical-gap --manifest /tmp/dk-historical-gap/MANIFEST.csv --trigger local`

```
failed_reasons=game_evidence_missing:35,game_info_unparsed:1
selected=62 succeeded=26 failed=36 reused=0 not_selected=80 rows_read=27788 rows_valid=27773 rows_rejected=15
```

Exit 1.

| Check | Value |
|---|---|
| Snapshots | 26, all `full_export`, `draft_group_id` null, `optimizer_ready` not true |
| Snapshot seasons | 2022: 3, 2023: 12, 2024: 11 |
| `dknfl_salaries` rows | 7663 |
| Ledger rows, including failed files | 27788 |
| `game_evidence_missing` | 35 |
| `game_info_unparsed` | 1 |
| DKNFL CSV artifacts / bytes | 62 / 2819068 |

The one `game_info_unparsed` file has a non-placeholder Game Info value that is not `AWAY@HOME date time ET`. Its CSV and ledger remain; it has no snapshot.

The 35 missing-evidence files do not have an exact `away_team`/`home_team`/`gameday` row. Thirty-four of them contain the token `LAR` on a date whose independent schedule row uses `LA` for the Rams. They stay rejected. One of those dates, 2024-01-14 `LAR@DET`, also has kickoff 20:15 in the file and 20:00 in the schedule, so it would still fail a clock check. No abbreviation crosswalk was applied, and those 35 are not successes.

### DFF companion readback on the same database

`python -m loader.dff_archive` on `seam_archive` exited 0: `selected=80 succeeded=80 failed=0 rows_read=17026`.

For all 80 manifest-selected DFF files, the snapshot metadata `companion_sha256` and `companion_artifact_id` were read back. The artifact row is `source=dff`, `artifact_kind=html_gzip`, and `sha256(body)` equals the stored `sha256`, the metadata hash, and the SHA-256 of the staged `evidence/dff-{season}-week{ww}.html.gz` bytes. Result: 80/80. The hash values are not copied here.

### Rerun on a fresh database after the f9f1dfb merge

Isolated `seam_validate` was migrated to `0007` and loaded from the same staged nflverse mirror (`games.parquet` sha256 `0bc6e1221d68535848e58b37c3adf298907be2a3759f7d3abb986c7e7f8587e2`, version `2026-11-06 20:46:43 EST`; teams sha256 `46955c6de3ff83e6ce229d278bc56a7772be287854f4b3a9666b151339568266`, version `2026-03-27 11:49:45 EDT`). `loader.run.main` wrote teams 36 and games 2021–2025 REG+POST plus 2026 REG (2022 REG is 271; the other REG seasons are 272). Season and week were not taken from folder names, and no game row was synthesized from a salary line.

With `games` still empty, the same archive command exited 1: `selected=62 succeeded=0 failed=62`, `failed_reasons=game_evidence_missing:61,game_info_unparsed:1`, snapshots 0, ledger 27788. That negative result was kept.

After the schedule load, the same command exited 1:

```
failed_reasons=game_evidence_missing:35,game_info_unparsed:1
selected=62 succeeded=26 failed=36 reused=0 not_selected=80 rows_read=27788 rows_valid=27773 rows_rejected=15
```

Snapshots 26, all `full_export`, `draft_group_id` null, `optimizer_ready` not true. Seasons 2022: 3, 2023: 12, 2024: 11. `dknfl_salaries` 7663 valid rows. A second pass over the 62 files against `public.games` counted matched 26, `LAR`-token-only misses 34, one other missing file, and 1 unparsed. No `LAR`→`LA` alias was applied. Not a certified season.

DFF on that database exited 0: `selected=80 succeeded=80 failed=0 rows_read=17026`. Database readback of companion artifact id, kind `html_gzip`, source `dff`, and body SHA-256 against the staged gzip files: 80/80. Private HTML hashes are not listed here.

## Contract correction: Position and Roster Position together

Classic eligibility was reading only `Roster Position`. With kickoffs that match `public.games`, `Position=CPT` / `Roster Position=FLEX` and `Position=QB` / `Roster Position=FLEX` both exited 0 and published snapshots. `test_position_and_roster_must_agree` was red on that behavior.

CPT in either column is now `showdown`. QB and DST must appear in their own roster tokens. A roster token that names a different primary position, such as `QB/FLEX` on an RB, is `unsupported_roster`. The failed files keep their CSV artifact and two ledger rows. The earlier two-game snapshot and its salary rows stay. No `LAR`→`LA` alias was added; the 35 missing-game files above remain fail-closed.

`DATABASE_URL=postgresql:///seam_f007_fix pytest -q` with trust authentication: `221 passed, 2 skipped`. `alembic heads` is `0007`. AT5 and AT6 still pass. This does not turn the 26-of-62 archive load into a certified season.

## Contract correction: every eligibility token

`Position=RB` with `Roster Position=RB/QB`, and `Position=QB` with `Roster Position=QB/FLEX`, still exited 0. A single matching primary token was enough. `test_every_roster_token_must_fit_position` was red on that.

QB and DST now allow only their own token. RB, WR, and TE allow themselves and FLEX, and every token must be in that set. Both counterexamples fail `unsupported_roster`, keep the CSV artifact and two ledger rows, and leave the earlier two-game snapshot in place. CPT and a roster that omits QB or DST were already closed.

## Team alias at the archive parse boundary

The 62 `DKSalaries*.csv` files in the public pureslurp/DKNFL tree were read locally and were not committed. Team tokens in `TeamAbbrev` and `Game Info`:

| Token | Files | Mapping |
|---|---|---|
| LAR | 35 | `LA`, the code those games use in the loaded schedule |
| WAS | 36 | none; the games table already uses WAS |
| JAX | 34 | none; already JAX |
| LV | 35 | none; already LV |
| LAC | 30 | none; already LAC |
| STL, SD, OAK, WSH, JAC | 0 | not mapped |
| FA | 1 | not a game token; one row has `Game Info` `-` |

`test_lar_token_matches_the_la_game` was red before the map: the file exited 1 with `failed_reasons=game_evidence_missing:1`. After `TEAM_ALIASES = {"LAR": "LA"}` it publishes, the snapshot games use `LA`, the ledger raw fields still say `LAR` and `LAR@KC`, snapshot metadata records `team_aliases: {"LAR": "LA"}`, and `team_raw` is `LA`. `test_unknown_team_token_fails_closed` keeps `ZZZ` on `game_evidence_missing` with no snapshot. No other alias was added, so there is no further alias test.

Isolated `seam_dknfl62`, flag-on migrate through `0008`, teams and games for 2021–2026 from a local nflverse mirror, then `python3 -m loader.dknfl_archive --archive-root /tmp/dknfl-public --manifest /tmp/dknfl-manifest.csv --trigger local` before the map:

```
failed_reasons=game_evidence_missing:35,game_info_unparsed:1
selected=62 succeeded=26 failed=36 reused=0 not_selected=0 rows_read=27788 rows_valid=27773 rows_rejected=15
```

The same command on a fresh `seam_dknfl_after` after the map:

```
failed_reasons=game_evidence_missing:1,game_info_unparsed:1
selected=62 succeeded=60 failed=2 reused=0 not_selected=0 rows_read=27788 rows_valid=27773 rows_rejected=15
```

Remaining failures:

| File | Reason |
|---|---|
| `2023/WEEK19/DKSalaries-Week19.csv` | `game_evidence_missing`. The file's `LAR@DET` on 2024-01-14 is 8:15PM; the schedule row for `LA@DET` that date is 20:00. The alias does not change the clock. |
| `2024/WEEK1/DKSalaries-Week1.csv` | `game_info_unparsed`. One row is `TeamAbbrev=FA` and `Game Info=-`. |

This is not a certified season. Mutator is not installed: UNKNOWN.

`ruff check loader web tests migrations` passed. `DATABASE_URL=postgresql:///seam_alias pytest -q` with local trust authentication, then restored to peer: `266 passed, 2 skipped`. `alembic heads` is `0008`.
