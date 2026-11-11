# ADR 0011: Allowlisted dataset query grammar, exact counts and bounded scan strategy

## Status

Proposed (2026-11-11 America/New_York). Next free ADR verified after 0010 on main `f5324a4`. Product request is Cosmo approval relayed by Groko at 07:57 ET, not independent architecture acceptance. No implementation, production migration or deployment authorized by this document.

## Context

F011 rich controls operate only on one API page. Five existing public lists have fixed filters, a single `sort`/`order`, offset/limit<=500, exact counts, explicit resource metadata and strict unknown-parameter rejection. The stats list joins public players for display name. Private salary relations and web-role grants cannot change. Neon Free makes repeated exact counts, substring scans and speculative indexes material costs. A client crawl would turn UI interactions into unbounded transfers and misrepresent partial results.

## Decision

Add `sorts`/`filters`/`search` only to existing list endpoints with the exact grammar and exhaustive per-endpoint public registry in [F012](../features/F012-dataset-query/SPEC.md). Keep legacy-only requests byte-shape/semantic compatible, including old null placement/errors. Presence of new params explicitly selects advanced behavior: max three user sort keys, native types/null-last plus unique-key tiebreaks; AND-combined legacy filters and typed bounded column filters; escaped literal case-insensitive contains over a fixed text search set.

Use parameter-bound SQLAlchemy Core. Exact count and page share one short read-only repeatable-read snapshot and filtered relation; count remains correct even for offsets beyond total. Retain offset/limit and response envelope. Bound advanced SQL execution to 3000ms with transaction-local timeouts and two concurrent transactions per app process; timeout/busy have explicit no-store 503s. This is not a global rate limiter.

Start with existing predicate indexes plus two stats B-tree indexes: default PPR descending/null-last + unique key, and exact season/type/week + PPR order. Full definitions and evidence gates are in F012/data dictionary. No pg_trgm/GIN or per-column index explosion. Contains/global search may scan within the deadline; index-only DDL is written by forge and needs separate Cosmo approval before production, with lock/space checks and automatic refresh-migration paths accounted for. No web grants changes.

Wire UI in separate [F013](../features/F013-dataset-table-controls/SPEC.md), after F012 and F011 merge. Explicit page/dataset scope preserves old links instead of silently changing search meaning. Dataset mode maps normalized F011 state to server grammar and disables client sorting/filtering; layout/virtualization and explicitly page-only CSV remain. Dataset-wide CSV deferred.

## Reasoning

A small typed query language earns its validation/compiler boundary: columns/operators never become raw SQL. Opt-in avoids redefining old parameters, especially players `q` and descending null behavior. Exact totals retain existing pager expectations; one snapshot avoids count/page races without long-lived cursor state. Explicit tie keys stabilize unchanged datasets, not concurrent refreshes across requests.

Two matching B-tree paths improve the common stats order/cohort queries without implying arbitrary sort/filter combinations are free. Fixed text sets and escaping avoid wildcard surprises and unsupported full-text promises. Initial bounded scans trade occasional honest timeout for lower storage/write amplification; local synthetic plans must expose poor cases. Frontend debouncing, cancellation, no retry loops and page-only export reduce repeated compute/egress but are not security controls against all public traffic.

## Rejected alternatives and why

- Reuse comma-delimited `sort` or broaden players `q`: breaks validated legacy grammar/semantics and error strings.
- Make all existing requests null-last/repeatable-read by default: unnecessary compatibility risk; opt in explicitly.
- Download every page and sort/filter in the browser: unbounded work/egress, stale partial results, defeats pagination.
- Accept SQL expressions, dynamic table names or discover future columns automatically: weakens the public-data/security boundary.
- Global search over every scalar cast to text: broad, scan-heavy and unclear; keep fixed text columns and explicit individual filters.
- Install pg_trgm and a GIN for every text field now: storage/loader overhead and extension DDL without measured need. Reconsider via evidence-backed docs revision.
- Estimate/cached totals or only COUNT OVER: estimates change pager contract; window counts alone lose total on empty offset pages.
- Keyset pagination/cross-request snapshots: larger incompatible client contract; unique ties plus documented refresh limits suffice here.
- Dataset-wide CSV, even streamed or conditionally small: quotas, response bytes, consistency and abuse controls need a separately scoped feature; streaming does not bound database work.
- Paid cache/search service, new API version, new host or elevated web role: unnecessary cost/scope/permission changes.

## Consequences

Two small build passes: F012 backend, then F013 UI. Current page links and CSV remain honest. Advanced matching uses database locale, not guaranteed identical JS locale behavior; UI explains narrowed search scope. Exact count is potentially expensive and may timeout; users narrow filters rather than receive estimates. Index storage and write amplification must be recorded on synthetic data, and production headroom measured separately with approval. No salary/public data expansion, no grant change, no automatic production migration. Existing real-Postgres/API/grant/CI and exact attribution requirements stay intact. Accepted ADR 0010 records the F010/F011 baseline; F012/F013 extend it without editing its decision substance or changing the constitution.
