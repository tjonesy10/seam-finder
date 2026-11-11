# F012: Dataset-wide public query contract

Status: **READY** (2026-11-11 America/New_York). Planning only, read against main `f5324a4`. Cosmo's follow-up approval at 2026-11-11 07:57 ET is **relayed by Groko**, not independently received here. Build only after F011's implementation merges. [F013](../F013-dataset-table-controls/SPEC.md) is a separate frontend pass after F012 merges. Owner merges; production migrations need separate Cosmo approval.

## Problem / job to be done

F011's rich controls see only one API page. Analysts need sorting/filtering/search before pagination without downloading a dataset or expanding the public data boundary. Deliver the bounded server contract in one pass, then wire controls in F013. Existing five list URLs, response shapes and old query semantics remain valid.

## Requirements

- **R1** Extend only the five existing public list endpoints with an explicit allowlisted advanced query grammar; retain all legacy-only behavior, detail/root/health contracts and rejection of unknown parameters.
- **R2** Support up to three ordered sort keys, deterministic null-last ordering and unique-key tiebreaks before pagination on the advanced path.
- **R3** Support per-column literal text contains/equals, inclusive numeric ranges and multi-selects with missing-value selection; combine legacy and advanced constraints without broadening either.
- **R4** Support literal global search across a fixed per-endpoint text set; no SQL, regex, wildcard, ranking or automatic column discovery.
- **R5** Validate size/types/columns/operators at the request boundary before database access, using existing JSON 400 envelope and deterministic bounded error messages.
- **R6** Return exact filtered totals and rows from one short consistent database snapshot; retain limit 1–500 and existing offset range, including offsets beyond total.
- **R7** Execute parameter-bound SQLAlchemy Core queries with bounded advanced-path SQL time/concurrency; add only the explicitly planned indexes, with local/CI plan evidence and a separate production approval gate.
- **R8** Preserve public projection, salary isolation, web-role grants, exact attribution and hosting. No salary table, field, source or export becomes accessible.
- **R9** Document Neon compute/storage/egress and plan tradeoffs; do not claim every substring/multi-sort is index-backed or that this is abuse-proof.
- **R10** Supply real-Postgres acceptance evidence, unchanged legacy API on/off tests and boundary/grant gates; no production actions or frontend wiring in this pass.

## User stories

- As an analyst, I want all matching public rows ordered consistently, so that pagination does not conceal higher-priority matches.
- As an existing API client, I want my old links unchanged, so that this addition does not break integrations.
- As the operator, I want expensive queries bounded and visible in test evidence, so that a public table does not exhaust the free tier silently.

## Observable behavior

### Current contract and compatibility

Source inspected: `web/resources.py`, `web/params.py`, `web/queries.py`, `web/errors.py`, `web/main.py`, `loader/tables.py`, migrations and `tests/test_api.py` on `f5324a4`. Data types/keys: [data dictionary](../../data-dictionary.md). No column is added.

| List endpoint | Existing filters (unchanged) | Existing `sort` choices, in error-message order | Default sort/order | Unique tiebreak |
|---|---|---|---|---|
| `/api/teams` | `conf`, `division` | `team_abbr`, `team_name` | `team_abbr` asc | `team_abbr` |
| `/api/players` | `q`, `position`, `team`, `status` | `display_name`, `position`, `latest_team`, `rookie_season` | `display_name` asc | `gsis_id` |
| `/api/games` | `season`, `week`, `season_type`, `team` | `gameday`, `week`, `season` | `gameday` asc | `game_id` |
| `/api/player-week-stats` | `season`, `week`, `season_type`, `team`, `position`, `player`, `game_id` | `fantasy_points_ppr`, `fantasy_points`, `passing_yards`, `rushing_yards`, `receiving_yards`, `receptions`, `targets`, `week`, `season` | `fantasy_points_ppr` desc | `gsis_id`, `season`, `week` |
| `/api/load-runs` | `dataset`, `status`, `season` | `started_at` | `started_at` desc | `id` |

Legacy parser stays: trim blanks to absent; `season` integer 1999–2100, `week` 1–22, team 2–3 letters uppercase, position 1–5 letters uppercase, season_type REG/POST case-normalized; `q` 2–50 characters, other bounded legacy text <=64; `order` case-insensitive asc/desc; limit default 50, offset default 0, offset maximum 2147483647. Legacy duplicate scalar parameters retain current last-value behavior. Preserve old error messages exactly, including sort choice order. `q` remains players display-name-only escaped ILIKE; games `team` remains home OR away; all other predicates stay as implemented.

Only list endpoints accept new `sorts`, `filters`, `search`. Their presence (even empty) selects the advanced path. With none present, use the existing path unchanged, including native Postgres null placement (descending can put nulls first), database collation, ties, count behavior, headers and Jinja rollback. Do not impose advanced null ordering on old requests. New params remain unknown on root, health and details, and on legacy Jinja page queries (shared parsers must keep the JSON-list opt-in boundary). Browser `ui_*` params remain unknown on the API.

Validate legacy parameters even when an advanced sort supersedes them. Nonempty `sorts` overrides legacy `sort`/`order`; empty/absent `sorts` on an advanced request uses validated legacy/default single sort with advanced null-last semantics. Legacy filters AND with advanced filters/search, including constraints on the same column; contradictions give zero rows, never silent override.

### Grammar and bounds

Each new parameter is one URLSearchParams-encoded string, decoded once. Compact JSON recommended, not required. Parameter/column/kind/member names are case-sensitive. Duplicate JSON object members are invalid, including nested duplicates; no NaN/Infinity, boolean-to-number coercion, unrecognized members, SQL fragments or unlisted columns. Duplicate new top-level parameters are invalid; legacy duplicates stay unchanged. Reject nesting deeper than 8 containers as invalid JSON, before a recursion error can occur.

| Param | Shape / default | Bounds |
|---|---|---|
| `sorts` | JSON array of exactly `{ "id": columnKey, "desc": boolean }`; `[]` means legacy/default order | 0–3 entries, unique column keys |
| `filters` | JSON object keyed by filterable public column; default `{}` | <=16 columns |
| `search` | Trimmed literal text; blank means no search | 1–100 Unicode characters when nonblank |

Absent new params use defaults within advanced mode. Blank `sorts`/`filters` strings are invalid JSON. Combined UTF-8 byte length of decoded new parameter values must be <=8192 before trim; check before parsing. This is not a proxy URL-length guarantee; F013 separately bounds encoded URLs. Each text value is trimmed, <=100 characters. Each multi value is a trimmed nonempty string <=100 characters, <=64 entries before deduplication. NUL is invalid in any new string. Omit valid no-op filters in canonical requests.

Exactly one filter form per column:

- Text: `{"kind":"text","op":"contains","value":"..."}` or `op:"equals"`. For F011 compatibility, omitted `op` means contains; no other member is optional. Empty/whitespace value means no filter. Escape backslash, percent and underscore as literals for contains. Case-insensitive Postgres lower/ILIKE under configured database locale; no accent folding, stemming, regex or JS en-US comparator guarantee. Null never matches nonempty text.
- Range: `{"kind":"range","min":number|null,"max":number|null}`. Both bounds required; finite signed JSON numbers, absolute bound <=1000000000000, min<=max when both supplied. Inclusive raw comparison, no rounding/coercion of formatted strings. Both null means no filter; null never matches a bounded range. Numeric identifiers are not measures.
- Multi: `{"kind":"multi","values":string[],"missing":boolean}`. Both required. Case-insensitive equality using trimmed selections under the same database locale; deduplicate equivalent selections. OR within a column plus `IS NULL` when missing=true; AND across columns. Empty values + missing=false means no filter; empty + missing=true means only nulls. Valid absent selections match nothing, not an enum-validation error.

No arbitrary boolean tree or multiple operators per column. M columns below accept only multi, T only text, N only range. Global search does not depend on column visibility.

### Explicit public column registry

Sets are exhaustive, never introspected from future table columns. Every listed T/M/N column is sortable; filter operators are restricted to its set. Date/timestamp/boolean/UUID/identifier scalars in T use deterministic raw text for filters: ISO dates, UTC ISO timestamps with `+00:00`, lowercase true/false, canonical UUID, ungrouped decimal identifier. Sort by native SQL type, not this text representation. Text ordering uses configured database collation. `player_display_name` resolves only to the existing public players join. No incoming SQL expression, registry discovery from keys or advanced SELECT-star expansion.

| Endpoint | T: text contains/equals | M: multi-select | N: numeric range |
|---|---|---|---|
| teams | `team_abbr`, `team_name`, `team_nick`, `team_id`, `team_color`, `team_color2`, `loaded_at` | `team_conf`, `team_division` | none |
| players | `gsis_id`, `display_name`, `first_name`, `last_name`, `birth_date`, `college_name`, `pfr_id`, `espn_id`, `pff_id`, `nfl_id`, `esb_id`, `otc_id`, `is_stub`, `loaded_at` | `position`, `position_group`, `latest_team`, `draft_team`, `status` | `height`, `weight`, `rookie_season`, `last_season`, `years_of_experience`, `draft_year`, `draft_round`, `draft_pick` |
| games | `game_id`, `game_type`, `season_type`, `gameday`, `weekday`, `gametime`, `overtime`, `location`, `roof`, `surface`, `stadium`, `old_game_id`, `pfr`, `espn`, `loaded_at` | `away_team`, `home_team` | `season`, `week`, `away_score`, `home_score`, `result`, `total`, `spread_line`, `total_line` |
| player-week-stats | `gsis_id`, `player_display_name`, `season_type`, `game_id`, `loaded_at` | `team`, `opponent_team`, `position`, `position_group` | `season`, `week`, `completions`, `attempts`, `passing_yards`, `passing_tds`, `passing_interceptions`, `sacks_suffered`, `sack_fumbles_lost`, `passing_2pt_conversions`, `carries`, `rushing_yards`, `rushing_tds`, `rushing_fumbles_lost`, `rushing_2pt_conversions`, `receptions`, `targets`, `receiving_yards`, `receiving_tds`, `receiving_fumbles_lost`, `receiving_2pt_conversions`, `target_share`, `special_teams_tds`, `fantasy_points`, `fantasy_points_ppr` |
| load-runs | `id`, `run_group`, `trigger`, `started_at`, `finished_at`, `source_url`, `source_version`, `notes`, `error` | `dataset`, `status` | `season`, `rows_read`, `rows_upserted`, `rows_deleted`, `rows_skipped` |

Only current public output columns are listed; identifiers above are field names, not identifier literals. Retain current load-run diagnostic sanitization/projection; filtering notes/error is not permission for private diagnostic access.

Global search is OR of escaped ILIKE contains over the following exact text columns, with null contributing false; it ANDs with all filters. No concatenation/cross-column phrase matching or measure-to-text expansion:

| Endpoint | Global search columns |
|---|---|
| teams | `team_abbr`, `team_name`, `team_nick`, `team_conf`, `team_division` |
| players | `display_name`, `first_name`, `last_name`, `latest_team`, `position`, `position_group`, `college_name` |
| games | `away_team`, `home_team`, `stadium`, `game_type`, `season_type` |
| player-week-stats | `player_display_name`, `team`, `opponent_team`, `position`, `position_group` |
| load-runs | `dataset`, `status`, `trigger` |

No global numeric/identifier/date/notes/error search. Per-column filters remain available. This is deliberately narrower than F011 search-across-all-scalars; F013 labels the difference and does not silently reinterpret old links.

Example without personal records (decoded for readability; URLSearchParams encodes once): `/api/games?season=2026&sorts=[{"id":"week","desc":false},{"id":"total","desc":true}]&filters={"total":{"kind":"range","min":30,"max":null}}&limit=50`.

### Ordering, totals and errors

Advanced effective sorts use NULLS LAST in either direction. Append every missing unique-tiebreak column ascending in resource order; do not duplicate explicitly sorted keys. Three-user-key maximum excludes internal tiebreaks. Numbers sort numerically, dates/timestamps chronologically, booleans false before true. No client resort in dataset mode. On unchanged data, adjacent offset pages are deterministic/disjoint. Refreshes between requests can insert/remove/reorder; no cross-request snapshot/cursor guarantee.

Response stays `{data: row[], page: {limit: integer, offset: integer, total: integer}}`. `total` is exact count after all predicates and before LIMIT/OFFSET. Count and page SELECT use one READ ONLY REPEATABLE READ transaction with the same filtered relation and current stats join. No window-count-only implementation (empty offset pages still need total), materialized view, estimate or unfiltered count. Zero matches => data=[], total=0; offset>=total => data=[] with true total. End snapshot immediately after reads, never across UI paging.

Validation order: unknown top-level keys as today; legacy validation with existing precedence; new duplicate/size checks; then `sorts`, `filters`, `search`. Within JSON validate structure before columns; filter keys traverse lexically. Return one safe message, no submitted value, SQL, parser detail or traceback. New 400 shape: `{"error":{"code":"invalid_parameter","message":MESSAGE,"param":PARAM}}`.

| Failure | PARAM | Exact MESSAGE |
|---|---|---|
| Duplicate new top-level key | that key | `duplicate parameter: KEY` (substitute allowlisted name) |
| Combined decoded values >8192 bytes | `filters` | `advanced query exceeds 8192 bytes` |
| Invalid JSON/depth/duplicate member/outer shape | `sorts` or `filters` | `invalid sorts` / `invalid filters` |
| >3 keys, duplicate sort column, wrong type/members/direction or unknown column | `sorts` | `invalid sorts` |
| >16 filters, unknown field/kind/member, wrong column kind, invalid text/multi/range/NUL | `filters` | `invalid filters` |
| Search >100 nonblank characters or NUL | `search` | `invalid search` |

Unknown stays exactly `{"error":{"code":"unknown_parameter","message":"unknown parameter: foo","param":"foo"}}`, HTTP 400. SQL-like text is literal data; SQL-like column keys fail registry validation. Preserve `application/json; charset=utf-8` and existing `public, max-age=300` on success/400. Disconnect remains 503 `service_unavailable` / `The database is unavailable.`; permission/programming errors remain generic 500.

### Query execution, indexes and cost

Existing SQLAlchemy Core/psycopg only: fixed column expressions/operator enums, bound values, one filtered relation, SQL filtering/order/paging. No Python fetch-all, per-row queries, all-page loops or dynamic joins. Preserve pool/connect settings and legacy-only routes.

Advanced requests alone have a monotonic 3000ms SQL-execution budget starting immediately before transaction setup, not a cold-start/connection/network SLA. Before every database statement, set transaction-local `statement_timeout` to remaining budget; once expired start no further statement. SQLSTATE 57014 from this deadline => HTTP 503 `{"error":{"code":"query_timeout","message":"The query took too long. Narrow filters and retry."}}` with no param. Roll back/release connection; local settings cannot leak to pooled sessions. Set read-only isolation before snapshot reads; support transaction pooling without changing role/database defaults.

Allow at most two advanced database transactions per app process, admitted without waiting; saturation => HTTP 503 `{"error":{"code":"query_busy","message":"Too many dataset queries. Try again shortly."}}`. Release admission on success/error/cancellation. Legacy requests are outside this gate. Only new timeout/busy errors override middleware with `Cache-Control: no-store`; all existing response headers remain. F013 does not automatically retry. This is a per-process bound, not a distributed/IP rate limit or assurance against sustained traffic.

Forge authors one index-only Alembic revision (next migration number at implementation), exactly:

1. `ix_stats_public_ppr_order` on `public.player_week_stats (fantasy_points_ppr DESC NULLS LAST, gsis_id ASC, season ASC, week ASC)` for default full-dataset order.
2. `ix_stats_public_scope_ppr` on `public.player_week_stats (season ASC, season_type ASC, week ASC, fantasy_points_ppr DESC NULLS LAST, gsis_id ASC)` for exact cohort plus order.

No extension, generated column, table/view, permission, data rewrite or dropped index. These support reads but CREATE INDEX is DDL, **not a read-only operation**. Forge tests local/CI Postgres only. Production application needs Cosmo's separate explicit approval and reviewed locks/maintenance/storage-headroom plan. Docs merge is not that approval. Current refresh workflows run `alembic upgrade head`; do not trigger them for verification or allow implementation rollout to bypass production approval. Blueprint runs no migration. Use direct migration connections, not app pooled sessions.

Other combinations use predicate indexes plus bounded sorts or sequential scans; arbitrary three-key sorts are not promised index-backed. Existing lower(display_name) text_pattern_ops supports prefix, NOT `%contains%` ILIKE. Do not install pg_trgm/GIN now: accept bounded substring scans at current scale, profile before storage/write amplification. Additional needed indexes require a docs revision first, not speculative per-column indexes.

Neon planning references checked 2026-11-11: [plans](https://neon.com/docs/introduction/plans), [pricing](https://neon.com/pricing). Published Free allowances: 100 CU-hours/project/month, 1 GB database storage/project, 5 GB public network transfer/project/month, scale-to-zero after five idle minutes. Verify actual account allowance/headroom before production; not a measured account budget. Exact counts and contains scans cost compute even for 50 rows; typing can keep compute awake. LIMIT bounds rows/egress, not scan/count/sort work; deep offset costs work. Indexes consume shared storage and loader write work; cold/warm plans differ.

Implementation evidence: generate non-personal public-shape data (~250,000 stats/~25,000 players), analyze statistics, record Postgres version, fixture seed/row widths, index bytes (`pg_relation_size`), total DB bytes and EXPLAIN (ANALYZE, BUFFERS) for both count/page on: default order; exact season/type/week cohort; team/position+range+three sorts; selective/nonselective contains; joined display-name search; zero matches; deep offset. Record cold/warm conditions and individual elapsed times, not a universal promised latency. Verify intended index paths on matching shapes without disabling scans to manufacture a win. Costly scans may timeout; prove a selective query succeeds and timeout rollback is clean. Local/CI evidence only, no live Neon/private data. Account approval/headroom are production review inputs, not guessed measurements.

### Safety and CSV

Projections remain current public shapes including joined display name; no `salary_private`, F004 or any salary relation reads, even for malicious keys. `seamfinder_web` grants/default grants/memberships unchanged. No current public list/page exposes salaries; stats points remain nflverse, not DK points.

Exact every-page attribution stays: "Data: nflverse (nflverse-data), licensed CC BY 4.0. Changes: subset of columns, loaded into a database. Not affiliated with or endorsed by the NFL or nflverse. NFL data belong to their respective owners." Keep links to `https://github.com/nflverse/nflverse-data` and `https://creativecommons.org/licenses/by/4.0/`, including all F010/F011 states and `Last refresh: none` outage fallback. Future historical display would require exactly "Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). Not affiliated with DraftKings." No such display exists/is added, so no RotoGuru line is rendered.

Dataset-wide CSV is **deferred**, even when total<=500. No export endpoint, streaming response, fetch-all loop or hidden bulk download. Quotas, byte caps, snapshot duration and abuse controls deserve a separate feature. F011 guarded RFC 4180/formula-safe visible-column page export continues, <=500 rows, no attribution/comment rows. F013 retains explicit this-page export labeling. Streaming alone does not bound scan work/bytes.

## Acceptance tests

- **AT1 (R1, R10)** Given legacy-only requests on every list/root/health/detail with SPA on/off and Jinja rollback, when existing `tests/test_api.py` runs unchanged, then filters/sorts/null placement, duplicate scalars, errors, envelopes and headers stay identical.
- **AT2 (R1, R5)** Given new params on lists versus detail/root/health and unknown `foo`/`ui_*` on lists, when requested, then only list advanced names are accepted and unknown envelopes remain exact 400s before DB access.
- **AT3 (R2, R6)** Given synthetic ties/nulls and multiple pages on each endpoint, when one/two/three keys in both directions/reordered priorities are queried repeatedly, then null-last/native-type order, unique ties, disjoint pages and full sequence match SQL; fourth/duplicate keys fail 400.
- **AT4 (R1, R2)** Given legacy sort/order plus nonempty/empty advanced sorts, when combined, then nonempty overrides order, empty uses legacy/default null-last, invalid legacy values fail and legacy-only null placement stays unchanged.
- **AT5 (R3)** Given case variants/nulls/numeric boundaries, when text contains/equals, one/two-sided ranges and multi/missing combine with legacy filters, then literal matching, inclusive bounds, OR-within/AND-across, no-op forms and contradictory zero sets follow grammar on real Postgres.
- **AT6 (R4)** Given matches only in included/excluded/hidden fields and literal percent/underscore/backslash, when global search runs across five endpoints, then exactly fixed text OR-sets match and filters AND with them; no cross-column/wildcard/global numeric or diagnostic expansion occurs.
- **AT7 (R5)** Given invalid/deep/oversize JSON, duplicate members/new keys, wrong types/operators, boolean/nonfinite bounds, >16 filters, >64 selections, reversed ranges, NUL and Unicode byte/character boundaries, when parsed, then exact messages/precedence hold and invalid requests never query DB or cause recursion 500.
- **AT8 (R3, R5, R8)** Given SQL-like values/keys and attempts to name salary fields/relations, when requested on all endpoints, then values remain bound literals, bad keys fail 400, no private data/SQL detail escapes and existing projection/grant/boundary tests pass.
- **AT9 (R6)** Given concurrent synthetic writes between count/page, zero matches and offset>=total, when advanced queries execute, then snapshot-consistent exact totals/rows hold; later requests may see committed refreshes without cross-request guarantees.
- **AT10 (R7)** Given an expensive advanced query then a selective query reusing the connection, when budget expires, then exact no-store timeout 503 occurs, rollback/admission release work and settings do not leak; unrelated programming errors stay generic 500.
- **AT11 (R7)** Given two admitted advanced transactions, when a third arrives, then prompt exact no-store busy 503 occurs; success/error/cancellation frees capacity, with no role/pool config changes or retry loop.
- **AT12 (R7, R9)** Given both indexes on the fixed local synthetic workload, when count/page plans and sizes are collected, then intended order/cohort paths, other scan/sort tradeoffs and cold/warm timings are recorded honestly, without production access/speculative indexes.
- **AT13 (R8)** Given every page/state and metadata outage, when attribution/drift and existing permission tests run, then exact text/links/fallback persist, no salary/RotoGuru display appears, grants stay identical and private reads remain denied.
- **AT14 (R8, R9)** Given a total larger than the page and export actions, when reviewed, then no dataset export/API crawl exists; only bounded F011 guarded page CSV remains and LIMIT/streaming is not described as bounding query work.
- **AT15 (R7, R10)** Given implementation/migration/workflow diff and CI, when reviewed, then only specified index DDL is added by forge, grants/production stay unchanged, automatic migration paths are flagged for separate rollout approval and prior CI gates pass.
- **AT16 (R10)** Given TEST_REPORT.md, when audited, then every AT has automated/recorded evidence with real Postgres, raw API SPA on/off remains intact and no frontend wiring/deployment is claimed by F012.

## Non-goals

F013 frontend wiring, dataset CSV, facets/distinct-value endpoint, arbitrary SQL/boolean trees, keyset pagination, cross-request snapshots, estimates, pg_trgm/full-text/ranking, bulk loading, new public fields/sources, salary UI, auth, paid services, production migration/deploy. Legacy contracts are not retroactively hardened here.

## Allowed dependencies

Existing Python/FastAPI, SQLAlchemy Core, psycopg, Alembic, pytest; standard-library strict JSON validation and process-local admission primitives. No ORM, pandas, new service, extension or dependency. Frontend unchanged.

## Open questions

None. Grammar, scan/index strategy, exact count, bounds and CSV deferral are explicit planner decisions. Production approval is a later execution gate, not an unanswered product question. ADR 0011 stays Proposed until owner approval; READY means buildable specification, not accepted architecture/permission to deploy.

## ADRs

[0001](../../adr/0001-stack-and-hosting.md), [0002](../../adr/0002-nflverse-load-and-refresh.md), [0003](../../adr/0003-rotoguru-dk-classic-salaries.md), [0004](../../adr/0004-dk-current-slate-csv.md), [0005](../../adr/0005-private-salary-capture-and-archives.md), [0006](../../adr/0006-slate-safe-salary-unification.md), [0008](../../adr/0008-react-frontend-hosting.md), Accepted [0010](../../adr/0010-frontend-design-system-and-visual-checks.md); Proposed [0011](../../adr/0011-public-dataset-query-grammar.md). Private schedule/archive ADRs 0007/0009 remain unchanged. F012 adds opt-in API behavior, not a rewrite of F011's unchanged-API baseline.

## Analyze pass

| Requirement | Tests |
|---|---|
| R1 | AT1, AT2, AT4 |
| R2 | AT3, AT4 |
| R3 | AT5, AT8 |
| R4 | AT6 |
| R5 | AT2, AT7, AT8 |
| R6 | AT3, AT9 |
| R7 | AT10, AT11, AT12, AT15 |
| R8 | AT8, AT13, AT14 |
| R9 | AT12, AT14 |
| R10 | AT1, AT15, AT16 |

R1–R10 covered; AT1–AT16 none orphaned. Constitution/all ADRs checked against public-only queries, unchanged grants/stack/hosting, real-Postgres tests and owner-only rollout. No conflict/amendment. Advanced null placement/snapshot and narrow no-store errors are explicit additions, not legacy changes. Next free IDs verified: F012/F013 and ADR 0011 after main F011/0010; no competing open PR at planning read.
