# ADR 0003: RotoGuru as source for historical DraftKings NFL Classic salaries

## Status

Proposed (2026-11-06). Becomes Accepted only after Cosmo answers the license/attribution question and a constitution amendment covering this source is merged.

## Context

F001 loaded nflverse players, teams, games, and weekly stats. DFS backtests need historical DraftKings Classic weekly salaries and actual fantasy points. Cosmo approved using RotoGuru's public SCSV (`fyday.pl?game=dk&scsv=1`) for REG weeks 2015–2021, not current-slate DK files (F004) and not the optimizer. The public SCSV header and 2015 week 1 body were verified on 2026-11-06. The constitution today allows only nflverse-data under CC BY 4.0. RotoGuru's paid NBA/MLB master-file notes say personal use only / no commercial reproduction; the NFL weekly SCSV is publicly fetchable, but redistribution terms for a public hosted site are not clearly published there.

## Decision

1. **Source.** Fetch RotoGuru NFL DraftKings weekly SCSV over HTTP for each (season, week). Parse with a thin in-repo parser. Do not use `nfldfs`. Do not scrape draftkings.com.
2. **Scope.** Seasons 2015–2021, REG weeks only, Classic all-week slate salaries and points. No Showdown, no playoffs, no other DFS sites.
3. **Storage.** Table `dk_classic_salaries` keyed by `(season, week, rotoguru_gid)`, with mapped `gsis_id` / `team_abbr` and raw provenance columns.
4. **Load.** Idempotent per week (upsert + delete-missing) recorded in `load_runs` under dataset `dk_classic_salaries`.
5. **License gate.** No Accepted status and no forge handoff until Cosmo confirms we may store and publicly expose this data, with agreed attribution, and the constitution lists RotoGuru for this use.

## Reasoning

- RotoGuru is the widely used free historical Classic salary archive; Cosmo verified the endpoint.
- A thin parser avoids an unmaintained pin (`nfldfs==0.0.5`) and keeps behavior in-repo.
- Keeping `rotoguru_gid` plus raw name/team preserves provenance when name matching is imperfect.
- Blocking on license keeps the public repo aligned with the constitution.

## Rejected alternatives and why

- **Pin nfldfs:** Cosmo rejected; thin parser preferred.
- **Scrape draftkings.com:** Cosmo rejected; ToS and fragility.
- **Store salaries without gsis_id mapping:** blocks clean joins to F001 for backtests.
- **Treat as nflverse-adjacent without a new ADR:** false; different publisher and license.

## Consequences

- Constitution needs a short amendment naming RotoGuru historical Classic DK salaries as an allowed source under Cosmo's attribution rules.
- Footer/API attribution gains a RotoGuru line once wording is approved.
- Matching quality becomes a measured acceptance test; DST rows key by team only.
- F004 (current slate) remains a separate feature with its own source decision.
