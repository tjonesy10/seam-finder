# ADR 0003: RotoGuru as source for historical DraftKings NFL Classic salaries

## Status

Accepted (2026-11-06). License and attribution approved by Cosmo; constitution amendment merged via PR #10.

## Context

F001 loaded nflverse players, teams, games, and weekly stats. DFS backtests need historical DraftKings Classic weekly salaries and actual fantasy points. Cosmo approved using RotoGuru's public SCSV (`fyday.pl?game=dk&scsv=1`) for REG weeks 2015–2021, not current-slate DK files (F004) and not the optimizer. The public SCSV header and 2015 week 1 body were verified on 2026-11-06. The constitution today allows only nflverse-data under CC BY 4.0. RotoGuru's paid NBA/MLB master-file notes say personal use only / no commercial reproduction; the NFL weekly SCSV is publicly fetchable, but redistribution terms for a public hosted site are not clearly published there.

## Decision

1. **Source.** Fetch RotoGuru NFL DraftKings weekly SCSV over HTTP for each (season, week). Parse with a thin in-repo parser. Do not use `nfldfs`. Do not scrape draftkings.com.
2. **Scope.** Seasons 2015–2021, REG weeks only, Classic all-week slate salaries and points. No Showdown, no playoffs, no other DFS sites.
3. **Storage.** Table `dk_classic_salaries` keyed by `(season, week, rotoguru_gid)`, with mapped `gsis_id` / `team_abbr` and raw provenance columns.
4. **Load.** Idempotent per week (upsert + delete-missing) recorded in `load_runs` under dataset `dk_classic_salaries`.
5. **License / attribution.** Cosmo approved storing and publicly exposing this data (2026-11-06). Attribution exact: "Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). Not affiliated with DraftKings." ADR becomes Accepted when the constitution amendment is on main.
6. **Deliverable this pass.** Data-load only (schema, migration, loader, workflow, tests). Read API and browse pages are out of scope for F003; follow-up later.
7. **Mapping policy.** Explicit RotoGuru→nflverse team map (unmapped team fails the week). Unmapped skill rows keep null `gsis_id` and count in `load_runs.notes`; AT8 requires ≥98% match on non-Def rows with salary>0. DST keys by team only. Load `dk_salary=0` rows. Weeks: load 1–18 when SCSV returns; skip missing. Refresh: `workflow_dispatch` / manual only.

## Reasoning

- RotoGuru is the widely used free historical Classic salary archive; Cosmo verified the endpoint.
- A thin parser avoids an unmaintained pin (`nfldfs==0.0.5`) and keeps behavior in-repo.
- Keeping `rotoguru_gid` plus raw name/team preserves provenance when name matching is imperfect.
- Owner license approval unblocks the constitution amendment; F003 clarifications are closed and the SPEC is READY for forge (ADR stays Proposed until the amendment is on main).

## Rejected alternatives and why

- **Pin nfldfs:** Cosmo rejected; thin parser preferred.
- **Scrape draftkings.com:** Cosmo rejected; ToS and fragility.
- **Store salaries without gsis_id mapping:** blocks clean joins to F001 for backtests.
- **Treat as nflverse-adjacent without a new ADR:** false; different publisher and license.

## Consequences

- Constitution needs a short amendment naming RotoGuru historical Classic DK salaries as an allowed source under Cosmo's attribution rules.
- Public exposure of this data still needs the attribution line somewhere once pages exist. F003 itself does not add pages.
- Matching quality becomes a measured acceptance test; DST rows key by team only.
- Opponent code `-` currently fails the week under the unmapped-team rule; Cosmo should confirm whether `-` means bye/unknown and should load with null `opponent_abbr` instead (F003 follow-up).
- F004 (current slate) remains a separate feature with its own source decision.
