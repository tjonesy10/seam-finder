# Seam Finder constitution

Status: Accepted (2026-11-05); amended 2026-11-06 (RotoGuru / F003; current-slate DK export / F004; private salary capture, archives, and unification / F005–F008, owner-merged in PR #17); amended 2026-11-10 (React frontend / F009). Cosmo approved the 2026-11-10 amendment at 2026-11-10 20:03 America/New_York. The approved text is recorded in [CONSTITUTION-AMENDMENT.md](features/F009-react-frontend/CONSTITUTION-AMENDMENT.md) and references [ADR 0008](adr/0008-react-frontend-hosting.md). This 2026-11-10 amendment takes effect when the F009 follow-up PR merges to main. The non-negotiables every SPEC and ADR is checked against. Changed only through a PR the owner approves.

**Proposed cadence-text alignment (F014 docs):** the 10:07 wording below aligns the minute with merged PR #41 and the open PR #42 amendment (one `7 10 * * 3` America/New_York cron). This narrow constitution amendment takes effect only on owner merge of this docs change; it does not activate a schedule or approve production. [ADR 0013](adr/0013-refresh-before-lobby-capture.md) changes prerequisite ordering, not the approved slate or free-tier policy.

## Stack
- Python 3.12, FastAPI serving JSON under `/api/*` and the built React, TypeScript, and Vite static app, SQLAlchemy Core, Alembic, Postgres. The frontend uses TanStack Table, TanStack Virtual, and TanStack Query. It uses TanStack Router for page routes and URL-persisted filter, sort, and paging state. It does not use TanStack Start or SSR. Decided in [ADR 0001](adr/0001-stack-and-hosting.md), with the frontend and asset-hosting decision in [ADR 0008](adr/0008-react-frontend-hosting.md). Approved text: [CONSTITUTION-AMENDMENT.md](features/F009-react-frontend/CONSTITUTION-AMENDMENT.md).
- No ORM layer or pandas without a new ADR. The React, TypeScript, and Vite frontend and the TanStack libraries in [ADR 0008](adr/0008-react-frontend-hosting.md) are the allowed JS framework and bundler. No other JS framework, SSR framework, or bundler without a new ADR.

## Cost and accounts
- Free tiers only (Neon Free, Render Free, GitHub Actions on a public repo). Any paid plan, card on file, or new account needs the owner's approval first.

## Data and licensing
- Primary football data comes from nflverse-data under CC BY 4.0, with the attribution footer from [ADR 0002](adr/0002-nflverse-load-and-refresh.md) on every page.
- Historical DraftKings NFL Classic weekly salaries and points (REG, seasons 2015–2021) may be loaded from RotoGuru per [ADR 0003](adr/0003-rotoguru-dk-classic-salaries.md), stored in Neon, and shown on the public site with this exact attribution: "Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). Not affiliated with DraftKings."
- Current-slate DraftKings NFL Classic salaries from the owner's official `DKSalaries.csv` export may be stored in Neon for personal/optimizer use per [ADR 0004](adr/0004-dk-current-slate-csv.md). Do **not** publish raw salary tables or CSV downloads on the public site. Any UI that mentions DraftKings must say "Not affiliated with DraftKings." Never scrape draftkings.com, except the narrow F005 private capture below. [ADR 0005](adr/0005-private-salary-capture-and-archives.md) supersedes only that blanket auto-download ban for F005. F004's owner-export CLI, staged-path workflow, replacement behavior, Classic rejection, and privacy rules remain in force.
- F005 may automatically GET the allowlisted unauthenticated DraftKings NFL Classic live lobby/metadata/CSV as a private experiment, on the planned in-repo schedule Cosmo approved 2026-11-06: Wednesdays at 10:07 America/New_York during REG season, DST-correct, with GitHub's delay/drop and 60-day public-repo idle-disable caveats. Automatic selection is only the upcoming Sunday-afternoon Classic slate whose verified game set is exactly all REG games kicking off 1:00–4:30 PM America/New_York, including holiday weeks, with no Saturday or holiday substitution; a missing or ambiguous candidate fails closed. Each capture attempt stores private wall-clock start/finish and a monotonic duration in Neon. This schedule text does not by itself activate the workflow. No login, account cookies, CAPTCHA/challenge bypass, proxy rotation, or access-control evasion. Stop on 401/403/429/challenge and preserve previous success. This exception does not authorize general web scraping, historical-lobby crawling, or public republication.
- F006 may ingest the acquired Daily Fantasy Fuel dated HTML-row-extraction salary/projection subset archive; F007 may ingest the acquired pureslurp/DKNFL original salary CSV archive. They are separate third-party sources covered by ADR 0005, not RotoGuru or nflverse. No new scheduled harvesting or broader rights are inferred.
- All three new source tables, exact artifacts/rows (including rejected evidence), and the F008 unified salary surface are private/optimizer-only. Do not publish raw tables, CSV downloads, or source payloads via the public site, repository, Actions logs, or artifacts. Durable raw provenance lives privately in Neon, subject to bounded free-tier guards; no automatic purge or paid upgrade.
- F004 remains Cosmo's official-export CLI plus staged-path workflow with its existing keys/replacement behavior. The new source table does not replace it. Enforce existing privacy by denying the public web role access to F004 and raw private salary relations, including through default or blanket grants. A separate non-web read-only optimizer role may read the unified view; the web role may not inherit it. The loader remains the sole writer.
- F008 requires verified player and exact slate revision equivalence before applying source priority. One coherent anchor snapshot defines each pool; no missing-player filling across snapshots or slates. Preserve mapping versions, disagreements, and all original provenance. Vendor IDs are not interchangeable. Legacy F003 weekly rows and unverified F004 current evidence cannot silently become known historical main slates.
- No optimizer implementation, new APIs/UI, auth, other sports, paid feeds, or production rollout is approved with these sources. Existing nflverse/RotoGuru attribution and public permissions remain unchanged. Any future UI mentioning DraftKings must keep "Not affiliated with DraftKings." Public redistribution of these new sources requires separate owner approval and rights review.
- No team logos, player headshots, or share-alike (CC BY-SA) datasets without a new ADR. No other third-party salary feeds without a new ADR. F004 owner export is covered above. F005–F007 sources are covered by ADR 0005.

## Security
- The repo is public. Secrets live only in GitHub Actions secrets and Render environment variables, never in files, logs, or examples.
- The web app connects with a read-only database role. The loader is the only writer.

## Testing bar
- Every acceptance test in a SPEC has an automated test or a recorded hand check in TEST_REPORT.md.
- Tests run against a real Postgres, not mocks of it.
- CI (ruff, pytest, gitleaks, and the F009 frontend typecheck, lint, unit, build, and Playwright checks) is green before a PR merges. The new frontend checks do not replace ruff, pytest, or gitleaks.

## Process
- `main` changes only by PR; the owner merges.
- A SPEC is READY with no open questions before code starts. When built work shows a spec was wrong, the docs are fixed first.
- Significant design decisions get an ADR. Accepted ADRs are superseded, not edited.

## Out of scope until planned
- Auth, user accounts, write APIs, live in-game data, and parts 2-5 (projections, valuation, DFS, live data) until each has its own SPEC. F005–F008 have SPECs for private salary capture, archives, and the unified read surface. Those SPECs do not approve an optimizer, a public salary API, schedule activation, or a production rollout.
