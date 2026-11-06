# Seam Finder constitution

Status: Accepted (2026-11-05); amended 2026-11-06 (RotoGuru / F003; current-slate DK export / F004). The non-negotiables every SPEC and ADR is checked against. Changed only through a PR the owner approves.

## Stack
- Python 3.12, FastAPI with Jinja2 pages, SQLAlchemy Core, Alembic, Postgres. Decided in [ADR 0001](adr/0001-stack-and-hosting.md).
- No ORM layer, pandas, JS framework, or bundler without a new ADR.

## Cost and accounts
- Free tiers only (Neon Free, Render Free, GitHub Actions on a public repo). Any paid plan, card on file, or new account needs the owner's approval first.

## Data and licensing
- Primary football data comes from nflverse-data under CC BY 4.0, with the attribution footer from [ADR 0002](adr/0002-nflverse-load-and-refresh.md) on every page.
- Historical DraftKings NFL Classic weekly salaries and points (REG, seasons 2015–2021) may be loaded from RotoGuru per [ADR 0003](adr/0003-rotoguru-dk-classic-salaries.md), stored in Neon, and shown on the public site with this exact attribution: "Historical DraftKings Classic salaries and points via RotoGuru (rotoguru1.com). Not affiliated with DraftKings."
- Current-slate DraftKings NFL Classic salaries from the owner's official `DKSalaries.csv` export may be stored in Neon for personal/optimizer use per [ADR 0004](adr/0004-dk-current-slate-csv.md). Do **not** publish raw salary tables or CSV downloads on the public site. Any UI that mentions DraftKings must say "Not affiliated with DraftKings." Never scrape draftkings.com.
- No team logos, player headshots, or share-alike (CC BY-SA) datasets without a new ADR. No other third-party salary feeds without a new ADR (F004 owner export is covered above).

## Security
- The repo is public. Secrets live only in GitHub Actions secrets and Render environment variables, never in files, logs, or examples.
- The web app connects with a read-only database role. The loader is the only writer.

## Testing bar
- Every acceptance test in a SPEC has an automated test or a recorded hand check in TEST_REPORT.md.
- Tests run against a real Postgres, not mocks of it.
- CI (ruff, pytest, gitleaks) is green before a PR merges.

## Process
- `main` changes only by PR; the owner merges.
- A SPEC is READY with no open questions before code starts. When built work shows a spec was wrong, the docs are fixed first.
- Significant design decisions get an ADR. Accepted ADRs are superseded, not edited.

## Out of scope until planned
- Auth, user accounts, write APIs, live in-game data, and parts 2-5 (projections, valuation, DFS, live data) until each has its own SPEC.






## Proposed amendment: private salary capture, archives, and unification (pending owner approval)

**Not effective before Cosmo approves and merges this docs PR.** Existing accepted rules above remain the active baseline until then. [ADR 0005](adr/0005-private-salary-capture-and-archives.md) and [ADR 0006](adr/0006-slate-safe-salary-unification.md) are Proposed; planning authorization is not production deployment/migration approval.

Upon that explicit approval, amend only the blanket “Never scrape draftkings.com” policy for the following narrow exception and add the following permitted sources/controls:

- F005 may automatically GET the allowlisted unauthenticated DraftKings NFL Classic live lobby/metadata/CSV as a **private experiment**, on the planned in-repo schedule Cosmo approved 2026-11-06: Wednesdays at 10:00 America/New_York during REG season, DST-correct, with GitHub's delay/drop and 60-day public-repo idle-disable caveats. Automatic selection is only the upcoming Sunday-afternoon Classic slate whose verified game set is exactly all REG games kicking off 1:00–4:30 PM America/New_York, including holiday weeks, with no Saturday or holiday substitution; a missing or ambiguous candidate fails closed. Each capture attempt stores private wall-clock start/finish and a monotonic duration in Neon. Approving this amendment does not by itself activate the workflow. No login, account cookies, CAPTCHA/challenge bypass, proxy rotation or access-control evasion. Stop on 401/403/429/challenge and preserve previous success. This exception does not authorize general web scraping, historical-lobby crawling or public republication.
- F006 may ingest the acquired Daily Fantasy Fuel dated HTML-row-extraction salary/projection subset archive; F007 may ingest the acquired pureslurp/DKNFL original salary CSV archive. They are separate third-party sources covered by ADR 0005, not RotoGuru or nflverse. No new scheduled harvesting or broader rights are inferred.
- All three new source tables, exact artifacts/rows (including rejected evidence), and F008 unified salary surface are private/optimizer-only. Do not publish raw tables, CSV downloads or source payloads via the public site, repository, Actions logs or artifacts. Durable raw provenance lives privately in Neon, subject to bounded free-tier guards; no automatic purge or paid upgrade.
- F004 remains Cosmo's official-export CLI plus staged-path workflow with its existing keys/replacement behavior. The new source table does not replace it. Enforce existing privacy by denying the public web role access to F004/raw private salary relations, including through default/blanket grants. A separate approved non-web read-only optimizer role may read the unified view; the web role may not inherit it. The loader remains the sole writer.
- F008 requires verified player **and exact slate revision** equivalence before applying source priority. One coherent anchor snapshot defines each pool; no missing-player filling across snapshots or slates. Preserve mapping versions, disagreements and all original provenance. Vendor IDs are not interchangeable. Legacy F003 weekly rows and unverified F004 current evidence cannot silently become known historical main slates.
- No optimizer implementation, new APIs/UI, auth, other sports, paid feeds or production rollout is approved by this amendment. Existing nflverse/RotoGuru attribution/public permissions remain unchanged. Any future UI mentioning DraftKings must keep “Not affiliated with DraftKings.” Public redistribution of these new sources requires separate owner approval and rights review.

ADR 0004's live file still says Proposed despite its earlier merged F004 amendment. Do not silently label it Accepted; review status-only cleanup separately. ADR 0005 proposes partial supersession of its blanket auto-download ban only, not its owner-export substance.
