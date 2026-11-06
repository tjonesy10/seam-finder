# ADR 0004: Current-slate DraftKings Classic salaries from Cosmo's CSV export

## Status

Proposed (2026-11-06). Blocked on Cosmo license / public-exposure answer and a constitution amendment if storage is approved.

## Context

F003 loaded historical Classic salaries (2015–2021) from RotoGuru. The product wedge needs **current** DraftKings NFL Classic salaries for a later optimizer. Cosmo can export `DKSalaries.csv` from DraftKings; scraping draftkings.com is forbidden. DraftKings terms restrict republication of their data; storing Cosmo's own export in a personal Neon database for tooling is a different question from publishing salaries on the public site.

## Decision

1. **Source.** Cosmo-supplied official Classic `DKSalaries.csv` only. No draftkings.com scrape. No `nfldfs` pin.
2. **Scope.** NFL Classic multi-game slates. Not Showdown. Not other DFS sites. Not the optimizer.
3. **Storage.** A dedicated current-slate table (proposed `dk_classic_slate`) keyed so loads are idempotent per slate identity (exact key pending SPEC clarification).
4. **Join.** Map to F001 `gsis_id` / `team_abbr`; keep DraftKings `ID` for later lineup export.
5. **License / exposure.** Pending Cosmo (SPEC Q1). Recommendation: allow Neon storage for personal/optimizer use; do not publish raw salary grids or CSV downloads on the public site; retain "Not affiliated with DraftKings."

## Reasoning

- Matches Cosmo's existing DK workflow (export CSV) and unlocks the optimizer path without ToS-hostile scraping.
- Separating F003 (historical RotoGuru) from F004 (current DK export) keeps licenses and refresh models clean.
- Keeping `dk_id` preserves a path to DraftKings bulk lineup upload formats later.

## Rejected alternatives and why

- **Scrape draftkings.com:** Cosmo / F003 already rejected; ToS and fragility.
- **Reuse RotoGuru for current weeks:** RotoGuru historical path is not the live export Cosmo uses for entering contests.
- **Pin nfldfs:** rejected for F003; same here.
- **Store only in local files, never Neon:** blocks shared joins with F001 in the deployed DB; worse for the optimizer unless Cosmo wants local-only (ask in Q1).

## Consequences

- Constitution Data section needs an amendment if Cosmo approves storing current DK export data.
- Public site must not casually dump DK salary tables if Q1 says private/optimizer-only.
- Forge implements loader + migration + tests only after SPEC clarifications close.
