# Schedule authority onboarding test report

Date: 2026-11-07. Branch `cursor/integrate-salary-stack-bb63`. Base `main` at `6417cd46f064abcb5a66b947d4204516ca75188f`. This report is engineer evidence for an independent gate. It is not a merge request and not a release claim.

## Ancestry

Normal merges, no rebase:

| Commit | Role |
|---|---|
| `6417cd46f064abcb5a66b947d4204516ca75188f` | current main, merge of PR 19 |
| `206edf7e0e739b451e7b3d12501cdb2e0357a1b3` | accepted F005 head, ancestor of main |
| `a61f4344e5fe0662d3bfd57b44d821bdb1982fc5` | accepted F006 head |
| `6157ff32c6175828bbce6616998aa50100c14f36` | PR 21 merge of F006 onto the F005 branch |
| `0e8ea789e5fc87f816d94f1b48477b3c6534b8c9` | accepted F007 head |
| `7cf02b991690f7a8498b316517556c054cd0c728` | PR 22 merge of F007 onto the F006 branch |
| `45a110cd6f2f59da61d0512739ff9e7fd3f3dd63` | accepted F008 head |
| `47a1f434f1a70a4ef4c5e367d5592f770b03cfa2` | PR 24 merge of F008 onto the F007 branch |

`git merge-base --is-ancestor` for each of those commits against the integration branch returned success before the workflow commit. F006, F007, and F008 `HANDOFF.md` files match those accepted heads byte for byte. The F005 handoff kept every prior line and appended one line for this integration.

`alembic heads` prints `0008 (head)` only. `0006` revises `0005`, `0007` revises `0006`, `0008` revises `0007`.

## Commands

`ruff check loader web tests migrations` — All checks passed.

`gitleaks detect --source . --redact --no-banner --log-opts=--all` — 82 commits scanned, no leaks found, exit 0.

`mutator` is not on `PATH`. `/agent/repos/crapper` is absent. Mutator advisory: UNKNOWN. It was not installed.

`DATABASE_URL=postgresql:///seam_f008 pytest -q` against local Postgres, not production.

First run, local `pg_hba` still `peer`: `263 passed, 2 skipped`, and `tests/test_readonly.py::test_at18_read_only_role` failed with HTTP 503. That is the existing peer-auth behavior of the read-only role check.

Second run after switching local auth to `trust` for the suite and restoring `peer` afterward: `264 passed, 2 skipped`. The eight new tests in `tests/test_schedule_authority_install.py` are included.

## What those tests showed

| Check | Result |
|---|---|
| Refresh Load binds `SALARY_PRIVATE_MIGRATION` and `DK_SCHEDULE_AUTHORITY_SHA256` to `${{ vars.<exact name> }}` | PASS |
| Capture binds `DK_SCHEDULE_AUTHORITY_SHA256` the same way and the job still requires `DK_LOBBY_CAPTURE_ENABLED == 'true'` | PASS |
| `dk-classic-slate.yml` matches main `6417cd46` | PASS |
| One Alembic head `0008`; flag-off targets stay `0003` from empty, `0005` from `0005`, and `0008` from `0008`; only exact `true` selects `head` | PASS |
| `maybe_emit_schedule_receipt` returns false when the flag is unset, when it is `TRUE`, and when the pin is unset | PASS |
| Install refuses a closed gate, an unreviewed root, a receipt document, and a wrong `--expect-sha`; games and artifact counts stay put | PASS |
| Synthetic reviewed root installs, readback matches the bytes, stdout says `installation_is_not_season_certification` and `pin_not_set`, and a second call reuses the artifact | PASS |
| Install against a database with no `salary_private` prints `private_schema_absent` and does not print the URL | PASS |
| Existing `test_flag_off_migrate_leaves_grants_unchanged` | PASS inside the 264 |
| Existing `test_production_migrate_stops_before_0004` with head `0008` | PASS inside the 264 |

The installed document used season `2099` and approval reference `synthetic-fixture-not-a-season-certification`. No real authority bytes were stored. `DK_SCHEDULE_AUTHORITY_SHA256` was unset during that test.

## Unverified

GitHub repository variable and secret values were not read and were not set. Production was not contacted. The reported production state, revision `0003` and no `salary_private`, was left untouched. No live DraftKings call, no capture activation, and no season certification.
