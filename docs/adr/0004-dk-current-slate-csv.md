# ADR 0004: Current-slate DraftKings Classic salaries from Cosmo's CSV export

## Status

Proposed (2026-11-06). License/exposure approved by Cosmo 2026-11-06. Becomes **Accepted** when the constitution amendment naming current-slate DK export storage is merged.

## Context

F003 loaded historical Classic salaries (2015–2021) from RotoGuru. The product wedge needs **current** DraftKings NFL Classic salaries for a later optimizer. Cosmo can export `DKSalaries.csv` from DraftKings; scraping draftkings.com is forbidden. DraftKings terms restrict republication of their data; storing Cosmo's own export in a personal Neon database for tooling is a different question from publishing salaries on the public site.

## Decision

1. **Source.** Cosmo-supplied official Classic `DKSalaries.csv` via CLI file path only this pass. No draftkings.com scrape. No upload UI this pass. No `nfldfs` pin.
2. **Pass scope.** Data-load only this pass (migration + table + CLI loader + tests). No read API or browse page.
3. **Unmapped skill.** Keep row with null `gsis_id`; count in load notes; AT ≥95% match on non-DST (DST may stay unmapped).
2. **Scope.** NFL Classic multi-game slates. Not Showdown. Not other DFS sites. Not the optimizer.
3. **Storage.** A dedicated current-slate table (proposed `dk_classic_slate`) keyed by `(season, week, dk_id)`. Cosmo passes `--season` and `--week` on each load.
4. **Join.** Map to F001 `gsis_id` / `team_abbr`; keep DraftKings `ID` for later lineup export.
5. **License / exposure.** Cosmo approved (2026-11-06): store in Neon for personal/optimizer use; do **not** publish raw salary tables or CSV downloads on the public site; retain "Not affiliated with DraftKings." ADR becomes Accepted when the constitution amendment is on main.

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

- Constitution Data section is amended in the same docs PR to name current-slate owner-export storage rules.
- Public site must not publish raw DK salary tables or CSV downloads.
- Forge implements loader + migration + tests only after SPEC clarifications close.
