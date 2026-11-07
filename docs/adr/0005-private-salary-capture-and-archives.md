# ADR 0005: Private live DK capture and attributed historical source archives

## Status

Accepted (2026-11-06) by owner merge of PR #17 (`6c26e8dad1f0261a29febaa2cd8311bb36aa893a`). Docs approval of this plan does not activate the schedule, run a migration, or change production.

Supersedes **only the blanket no-DK-auto-download policy** in ADR 0004 for F005's bounded unauthenticated capture. ADR 0004 is Accepted on status only. Its owner-export CLI/staged-path workflow, replacement semantics, Classic rejection, and privacy rules remain in force. Its decision text is not rewritten.

## Context

Cosmo requests four separate one-pass features: F005 live snapshots, F006 Daily Fantasy Fuel archive, F007 pureslurp/DKNFL archive, and F008 a unified private surface. Q1 answered option (a): a new append-only lobby table, keeping F004 unchanged as the official-export path. Existing constitution prohibits scraping and unnamed salary feeds. Public availability is not proof of redistribution rights; the experiment does not claim a license or reliable historical lobby retention.

Static evidence reviewed 2026-11-06: the local live experiment has a BOM-prefixed CSV with an extra Status column, 586 rows, 11 games, draft group 155994. Its raw draftables JSON contains 1,077 slot-expanded entries, **not** 1,077 independent salary players. The CSV is the salary authority. No collector was executed for this plan. The archive manifest has 80 DFF extraction CSVs (17,026 rows) and 62 original DK CSVs from DKNFL (27,788 rows); dates, path corrections, subsets, duplicates, and malformed rows are retained. Sources are not RotoGuru.

## Decision

Permit only F005's allowlisted unauthenticated NFL Classic live-lobby discovery and CSV GETs as a private experiment, separate from F004. Ingest the existing DFF and DKNFL archives offline into separate immutable private source tables; retain exact private artifacts, rejected rows, capture/load attempts, and versioned interpretations in Neon under the contracts in the data dictionary.

- F005: `salary_private.dk_lobby_salaries`; F006: `salary_private.dff_salaries`; F007: `salary_private.dknfl_salaries`. Shared artifacts/snapshots/attempts are private, not a combined salary source table. The shared dictionary retains evidence. Each source SPEC governs promotion. F005 publishes no usable snapshot when any salary is invalid; the raw artifact and parseable ledger remain. F006 and F007 may keep parsed non-ready snapshots and rejected rows only as their SPECs already allow. Successful parsing is not optimizer-ready completeness.
- Preserve F004 CLI and its existing Tuesday staged-file workflow. Never automatically invoke its upsert/delete-missing path on live captures.
- F005 cadence, approved by Cosmo via Groko on 2026-11-06 16:59 EST: Wednesday 10:00 America/New_York during REG season, DST-correct, no Sunday refresh. GitHub may delay or drop the run, and a public repository disables schedules after 60 days without activity. This approves planned schedule text only. It does not activate a workflow. Use in-repo GitHub Actions, not a bot routine.
- F005 automatic slate, approved by Cosmo via Groko on 2026-11-06 17:00 EST: only the upcoming Sunday-afternoon Classic draft group whose verified game set equals all REG games kicking off 1:00–4:30 PM America/New_York, including holiday weeks. No Saturday or holiday substitution. Exact game set and Classic rules must match. Missing or ambiguous candidates fail closed.
- Each F005 capture attempt persists private `started_at`, `finished_at`, and monotonic `duration_ms` in Neon, including success, failure, skip, and repeated content. Elapsed time is not inferred by subtracting wall clocks. A crash may leave finish and duration null; recovery must not fabricate completion. Public logs stay free of secrets and raw bodies. `load_runs` may hold compatible wall times only.
- Thin existing-stack HTTP client, no DraftKings login, cookie store, proxy rotation, CAPTCHA handling, anti-bot evasion, or third-party scraper dependency. Stop on 401/403/429/challenge; at most two retries for transient timeout/5xx, bounded per run. Do not retry 429 automatically, even if Retry-After is present; record it for a later deliberate run.
- Store raw CSV/JSON and archive extraction/companion evidence bytes in private Neon bytea artifacts. Public GitHub commits/logs and expiring Actions artifacts are not provenance stores. Synthetic fixtures only in the repo.
- Loader owns the private schema. Public web role has no USAGE/SELECT on it. A separate non-web read-only optimizer role may receive SELECT after owner approval. Remove the F004 table from blanket web grants; replace grant-all-public behavior with a positive public-table allowlist so a later refresh cannot undo isolation.
- No automatic deletion/retention purge. Conservative application limits: 5 MiB per stored object (including rejected body), 64 MiB total raw bytes per invocation, 128 MiB cumulative private artifact bytes and 512 MiB total database size write guard. These are safety budgets, **not** claims about current Neon allowances. Measure private tables plus indexes/TOAST and current account allowance before first load. Stop before exceeding either the guards or the verified free allowance. No paid upgrade without approval.
- Artifacts under the object limit are saved before parse validation, so rejected content remains attributable. For oversize bodies, stop reading at limit+1 and retain only bounded diagnostic metadata/hash of the retained prefix with `truncated=true`; never claim full retention or publish a snapshot. Administrative resolution is required; no silent truncation in source tables.

## Reasoning

Separate immutable sources preserve provenance and distinguish an official user export from an unofficial capture or vendor subset. Content hashes deduplicate bytes and parsed repeats without erasing repeated capture timestamps. Private Postgres avoids an extra paid storage/account dependency and loss of provenance when Actions artifacts expire. Bounded capture plus fail-closed validation preserves the last successful snapshot when an unofficial endpoint changes.

## Rejected alternatives and why

- Replace F004 with the lobby path: contradicts Q1(a), loses owner-export fallback and changes its existing contract.
- Browser/login scraping or bypassing rate limits: not authorized and not needed for the demonstrated unauthenticated experiment.
- Treat DFF as native DK CSV, actual scores, or complete Sunday main coverage: contradicted by evidence.
- Commit salary archives or rely only on runner disk/Actions artifacts: public exposure or expiring provenance.
- Scheduled ongoing DFF/DKNFL harvesting: not requested; these features ingest the acquired archive only.
- Use `nfldfs`, pandas, an ORM, or a new object-storage service: unnecessary dependencies/account changes.
- Interpret a successful public request as legal clearance: not justified. Keep private, stop if policy/access changes; public redistribution requires separate approval.

## Consequences

The constitution amendment is operative with the owner merge of PR #17. F005–F008 specs are READY. That approval does not activate the schedule or approve production migration or deploy. Build in separate PRs: F005 shared persistence/privacy and capture first; F006 and F007 only after that foundation PR merges; F008 only after those source PRs merge. Later features do not skip those merges. The order is not a new docs gate. Each build PR includes its acceptance tests and a Mutator report. F006/F007 need no live DK access. Storage caps can halt ingestion rather than evict raw history. Grant changes need real-Postgres regression tests. Future policy changes supersede this ADR; no public raw-salary API, page, or CSV download is authorized.
