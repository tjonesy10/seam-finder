# ADR 0009: Bounded DKNFL kickoff tolerance and free-agent row skips

## Status

Accepted (effective when PR #30 merges to main). Does not supersede [ADR 0005](0005-private-salary-capture-and-archives.md) or [ADR 0006](0006-slate-safe-salary-unification.md). No implementation, production load, or forge handoff is authorized until that merge. This acceptance does not certify a season.

## Approval

Cosmo (repo owner) approved on 2026-11-10 at 20:32 America/New_York (relayed by Groko), exact words: "I approve R7/R8 and ADR 0009 as written: 30-minute kickoff bound, schedule time canonical, 2% free-agent cap."

## Context

The F007 loader maps each parsed Game Info game to `public.games` by aliased home/away teams and America/New_York date, then requires an exact `gametime` match. Unparsed Game Info fails the whole file. After the documented `LAR` → `LA` alias, 60 of 62 staged pureslurp/DKNFL files load. Two still fail closed:

- `2023/WEEK19/DKSalaries-Week19.csv` is a Wild Card Classic file (POST, in F007 scope). `LAR@DET 01/14/2024 08:15PM ET` matches schedule game `2023_19_LA_DET` on that date, but nflverse `gametime` is `20:00` (delta +15 minutes). The file's other two games match exactly.
- `2024/WEEK1/DKSalaries-Week1.csv` has one row with `TeamAbbrev` exactly `FA` and `Game Info` exactly `-`, which is `game_info_unparsed`.

A scan of all 62 manifest files against nflverse `schedules/games.parquet` (local copy sha256 `4b5bf94644e192cb34d36f97db6729f22df13bdfc8c4ca93838a933ee63e1658`, `nflverse_timestamp` 2026-11-10 19:16:47 EST) found no other kickoff mismatch, no ambiguous team-date match, no date-only miss, and no other unscheduled `TeamAbbrev`. The only other empty Game Info rows are the 15 already-rejected 2021 week 2 placeholders. The free-agent row is 1 of 712 (0.14%). Week 19 is in scope because F007 already retains verified POST exports; excluding it would be the wrong fix.

Fail-closed exactness must not become silent data loss or an unbounded clock rewrite. F008 requires exact sorted game identities and kickoffs, so a tolerated file clock must not become a second slate identity.

## Decision

Adopt the F007 R7/R8 rules: tolerate a unique same-date, same-teams, manifest-agreeing schedule match when the absolute kickoff delta is at most 30 minutes, record the discrepancy, and use the schedule kickoff as the snapshot's canonical `kickoff_at`. Skip a row only when `TeamAbbrev` is exactly `FA` and `Game Info` is exactly `-`, audit and count it, and fail the file if those rows are more than 2% of its data rows. Any wider mismatch, ambiguity, or other unparsed Game Info still fails closed. Store audits in existing snapshot and observation metadata and ledger reason codes; add no column.

## Reasoning

The only archive kickoff disagreement is +15 minutes on one Wild Card game, which is broadcast-clock rounding against the schedule authority, not a different game. A 30-minute cap covers that case and leaves a small margin; it still fails a 31-minute or date-wrong row. Canonicalizing `kickoff_at` to the schedule keeps ADR 0006 slate identity stable. The FA pattern is a single, exact, non-game placeholder; auditing it in the ledger and metadata avoids silent drops while letting a 711-player Sunday file load. The 2% cap is far above the observed 0.14% and still fail-closed if a file is mostly placeholders. POST stays in scope, which the existing SPEC already requires.

## Rejected alternatives and why

- **Keep both files failing closed:** preserves exactness, but rejects a verified POST slate and a full week-1 export for one rounded clock and one placeholder. The evidence does not show a wrong-game risk at 15 minutes.
- **Treat week 19 as out of scope:** F007 already includes verified POST files, and the other four postseason files already match exactly. The defect is the clock rule, not scope.
- **Unlimited or hour-scale tolerance, or matching without a same-date check:** could attach a file to the wrong kickoff or the wrong day. Not fail-closed.
- **Store the file clock as canonical `kickoff_at`:** would split F008 slate identity from the schedule for the same game.
- **Skip every unparsed Game Info row, or any `FA` / any `-`:** broader than the observed pattern and could hide real parse failures.
- **Rewrite source bytes or omit the ledger row:** silent data loss, forbidden by ADR 0005 evidence retention.
- **Edit Accepted ADR 0005 or 0006:** those ADRs do not specify the exact-minute clock rule. This is an additive F007 matching decision.

## Consequences

F007 can load the two remaining staged files once this decision is accepted and implemented, with audits and a new `parser_version`. Exact matches and existing blank-placeholder rejection stay as they are. Over-bound clocks, ambiguous matches, and non-pattern unparsed rows still fail the file. Dictionary metadata fields record discrepancies and skips; no schema column is added. F008 consumers should use the canonical schedule `kickoff_at`. Acceptance is effective when PR #30 merges to main. It does not certify a season, authorize a production load, or hand the work to forge.
