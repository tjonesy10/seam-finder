# ADR 0010: Frontend design system and deterministic visual checks

## Status

Accepted (2026-11-10) by owner merge of PR #33, merge commit `3b61fcd`. Status-only synchronization; decision substance unchanged. Does not supersede Accepted ADR 0008; its stack/hosting remain. Acceptance does not authorize production actions.

## Context

F009 introduced the React/TypeScript/Vite SPA in `frontend/` without redesigning the parity UI. F010 needs a cohesive dark visual foundation; F011 adds richer interactions after F010 merges. The constitution permits this stack and requires existing backend and real-Postgres tests to stay. No API changes, private salary exposure, extra account or paid service is acceptable. Current Playwright writes screenshots but does not compare baselines.

## Decision

Use semantic CSS custom properties plus Vite CSS Modules, a fixed dark theme, native HTML controls and a small bundled Inter font subset; add no UI framework. Gate visual changes with Playwright screenshot comparisons against reviewed synthetic baselines in a pinned Chromium/Linux environment, plus dev-only axe scans, while keeping existing real-Postgres integration and API checks.

## Reasoning

- Tokens centralize contrast, spacing, typography and surfaces without runtime CSS generation. Modules contain component styling; Vite already supports them, so no new bundler or constitution amendment is needed.
- A fixed dark theme meets the immediate analytics redesign without doubling states/baselines for an optional light theme. A theme toggle is not necessary to deliver the job.
- `@fontsource/inter` contributes only bundled Latin normal-weight 400/500/600/700 font assets (OFL notice retained); no remote font request, account or font API. Wait for loaded fonts in visual tests. Reuse F010 tokens for F011.
- Native form/disclosure controls avoid a primitives dependency in this pass. This does not waive keyboard, focus or screen-reader obligations.
- Locked Playwright/browser, Ubuntu 24.04 visual runner, fixed desktop/mobile viewports, locale/timezone/time, synthetic route fixtures, disabled animation and loaded fonts make diffs reviewable. Threshold 0.2 and at most 100 differing pixels per image handle tiny raster differences without accepting broad drift. Missing baselines fail; CI never updates them.
- `@axe-core/playwright` is test-only, not a runtime framework. Zero WCAG 2.1 AA-tagged findings is an automated floor, not full conformance proof; keyboard/zoom/contrast checks supplement it.
- Route mocks isolate visual fixtures only. They do not replace API, grants, database or built-app integration tests against real Postgres.

## Rejected alternatives and why

- **Tailwind:** workable, but adds a utility/build vocabulary and dependency/configuration when custom properties plus built-in Modules cover a small six-route app. No measured benefit here.
- **MUI / Mantine / Chakra:** component/theme/framework surface is too large for five shared tables and a small shell; increases bundle and adapter/theming work. Not adding one quietly under this ADR.
- **Radix primitives:** smaller/headless and a reasonable future option for complex menus/dialogs, but native disclosure/forms suffice now. Reconsider through a scoped dependency decision if a demonstrated keyboard/focus need cannot be met simply.
- **CSS-in-JS:** runtime/style machinery with no requirement beyond static tokens/components.
- **Global CSS only:** fewer files initially, but repeated table/shell styles would share unintended selectors; keep globals restricted to tokens/base/accessibility utilities.
- **System or externally hosted fonts only:** system fonts vary across developers/CI and remote requests add nondeterminism/privacy/network dependencies. Bundle the small font subset instead.
- **Light and dark themes together:** doubles contrast and screenshot matrices without being required; defer light mode.
- **Uncompared screenshots / live production snapshots:** cannot gate regression reliably, and live records/timestamps are unstable and unsafe for public CI artifacts.
- **Mock-only testing:** violates the existing real-Postgres evidence requirement and misses API/grant regressions.

## Consequences

[F010](../features/F010-visual-redesign/SPEC.md) owns tokens, shell/states, responsive/a11y baseline and visual CI. [F011](../features/F011-premium-tables/SPEC.md) builds on that merged foundation with TanStack Table/Virtual interactions. Only new dependencies are the font asset package and dev-only axe; resolved versions/lockfile are committed by the engineer. Font files/license and synthetic baselines increase repository size modestly. Intentional visual changes need explicit baseline review in the pinned environment; browser/runner/font upgrades may require a separately reviewed baseline refresh.

Current public API pages are paginated and single-sort. F011 therefore labels rich operations as current-page-only, keeps existing dataset controls, and exports only the filtered logical current page; no whole-dataset crawling or new query contract. No salary fields are currently exposed, so salary controls remain absent. Existing exact nflverse footer and conditional RotoGuru attribution, private isolation, unchanged grants, and API/hosting contracts remain. No constitution amendment, paid service or production action is proposed.
