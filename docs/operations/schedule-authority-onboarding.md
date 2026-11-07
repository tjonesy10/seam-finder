# Schedule authority onboarding

This procedure stores operator-supplied schedule documents and reads them back. It is the installation step in [ADR 0007](../adr/0007-authoritative-schedule-completeness.md). Three separate facts stay separate:

- Independently reviewed authority evidence is the document bytes an operator already reviewed, including `approved_by`, `approved_at`, and `approval_reference` on an `authority_root_v1` body.
- Installation is `python -m loader.schedule_authority` writing those bytes into `salary_private.salary_artifacts` and reading the same bytes back by SHA-256.
- Season certification is a later human decision. The command does not make it. `DK_SCHEDULE_AUTHORITY_SHA256` is a separate repository or process setting, and this command does not write that setting.

No season inventory is certified by this document. Repository variable values were not read and were not set.

## Gates

Capture stays off unless the repository variable `DK_LOBBY_CAPTURE_ENABLED` is exactly `true`. The workflow compares that exact string and does not set it.

`python -m loader.migrate` applies revisions past `0003` only when `SALARY_PRIVATE_MIGRATION` is exactly `true`. Any other value, including an empty string or `TRUE`, leaves a fresh database at `0003` and leaves a database already past `0003` where it is. On this branch the flag-on target is Alembic head `0008`, in the order `0005` → `0006` → `0007` → `0008`.

The refresh Load step passes `SALARY_PRIVATE_MIGRATION` and `DK_SCHEDULE_AUTHORITY_SHA256` through from repository variables of those exact names. `loader.schedule_proof.maybe_emit_schedule_receipt` writes a receipt only when the flag is exactly `true`, the pin is present, and a stored inventory matches the raw object. An empty variable leaves the public games load running and writes no receipt.

The capture step passes `DK_SCHEDULE_AUTHORITY_SHA256` through the same way. An empty pin fails closed with `authority_unpinned` before any DraftKings call.

## Isolated install

Use a non-production database that already has `salary_private` from a flag-on migrate. Point `DATABASE_URL` at that database. Set `SALARY_PRIVATE_MIGRATION=true` for this process only.

```bash
SALARY_PRIVATE_MIGRATION=true python -m loader.schedule_authority \
  --file reviewed-authority-root.json \
  --expect-sha <sha256 of that file>
```

The file must already be one of `authority_root_v1`, `season_inventory_v1`, or `schedule_coverage_v1`, with the review fields ADR 0007 requires. A `schedule_source_receipt_v1` body is refused (`receipt_not_installable`). A root missing approval fields is refused (`document_unreviewed`). A SHA that does not match the file is refused (`sha_mismatch`) and nothing is stored. League reference bytes that are not those JSON documents can be stored with `--reference`; they are recorded as `schedule_reference` and are still not a certification.

Stdout contains the SHA-256, artifact id, document type, and kind, then the lines `installation_is_not_season_certification` and `pin_not_set`. It does not print the document body or `DATABASE_URL`.

Readback is part of the command. It loads the stored control artifact for that SHA and requires the bytes to match the file. A mismatch exits `readback_mismatch`.

The command does not read `public.games`, does not build `represented_source_ids`, does not insert a receipt, and does not change grants.

## Recovery point and forward repair

The recovery point for a games load is the succeeded `public.load_runs` row for dataset `games`, together with a private `schedule_source_receipt_v1` artifact whose `games_load_run_id` is that row when a receipt was emitted.

Forward repair is another ordinary games refresh, with `SALARY_PRIVATE_MIGRATION` exactly `true` and `DK_SCHEDULE_AUTHORITY_SHA256` set in that process to the operator-selected root SHA. The refresh fetches the current nflverse object and `maybe_emit_schedule_receipt` appends a receipt when the pinned inventory matches those bytes. Historical proof stays in place. This procedure has no production SQL and does not update `public.games` by hand.

## Grants and F004

Flag-off migrate does not create `salary_private` and does not call `loader.grants`. The web role allowlist remains `teams`, `players`, `games`, `player_week_stats`, `load_runs`, and `dk_classic_salaries`. Optimizer SELECT on `salary_private.dk_salary_unified` is applied only by a later grants run when `OPTIMIZER_ROLE` is set and the view exists. This procedure does not run grants.

`.github/workflows/dk-classic-slate.yml` is unchanged from main `6417cd46`. The Tuesday staged CSV path does not read `DK_SCHEDULE_AUTHORITY_SHA256`.

## Still manual

Setting `SALARY_PRIVATE_MIGRATION`, `DK_SCHEDULE_AUTHORITY_SHA256`, and `DK_LOBBY_CAPTURE_ENABLED` on the GitHub repository is a separate operator action. So is supplying a real reviewed league reference and choosing the pin. Production migration, a production load, a live DraftKings capture, and season certification are outside this procedure.
