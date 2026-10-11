# Changelog

All notable changes to ActionPilot are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Pre-publication security, accessibility, and dependency work committed after
the `v0.1.0` tag. Nothing here changes the tagged release.

### Security

- Run failures are persisted as a single bounded, redacted line
  (`ErrorType: message`) instead of a full stack trace, which
  `GET /api/runs/{id}` returned unauthenticated.
- Screenshot and video endpoints re-check every stored path against
  `runtime/` before opening it, so a poisoned database row cannot become an
  arbitrary file read.
- The phase-less browser-observation path now refuses non-local and
  non-`http(s)` URLs, matching the rest of the automation layer.
- A web-research plan without a web-research step returns `400` instead of an
  unhandled `500`.
- Agent plan and skill payloads are bounded (request length and step counts).
- Run titles mask secret-looking text, matching the audit log; the operational
  plan copy stays verbatim because approved runs resume from it.
- Frontend: research source links render as links only for `http(s)` URLs, and
  recorded-step messages are accepted only from the app's own origin.

### Changed

- Accessibility: run steps are keyboard-operable buttons; modals are dialogs
  with Escape-to-close and labelled close buttons; a skip link, live regions
  for run status/approvals/toasts, `aria-current` on navigation, and labels on
  all inputs were added; the decorative avatar is no longer a focusable button.
- The UI no longer imports Google Fonts — typography uses the system font
  stack, so the app loads no remote resources at all.
- The skill-run button label now matches its actual behaviour ("Run skill");
  memory empty-state and Routines schedule copy clarified; the memory delete
  button no longer stretches across the row.

### Dependencies

- `python-dotenv` 1.0.1 → 1.2.2, `pillow` 11.1.0 → 12.3.0, `pytest` 8.3.4 →
  9.0.3, and `source-map-js` 1.2.1 → 1.2.2. OSV.dev reports no advisories for
  any pinned backend package and `npm audit` reports none for the frontend.

### Testing

- 21 new regression tests (`backend/tests/test_security_hardening.py`);
  backend suite is 202 tests.

## [0.1.0] - 2026-10-11

First tagged release of the local-first workflow automation tool.

### Added

- **Recording and replay:** Manifest V3 browser extension (Chrome/Brave),
  reusable Skills in local SQLite, `{{variable}}` placeholders, per-step
  screenshots, run video, clickable run timeline, and standalone Playwright
  `.spec.ts` export.
- **Agent execution foundation:** Command box planning with tool registry
  (skills, Gmail, web research, browser, desktop), an execution loop with
  read-only observation before actions, verification of results, and persisted
  run state with pause/resume/stop.
- **Adaptive execution layer (milestones A–F):** runtime risk classification,
  authoritative approval gate (approve/reject; denial stops the run), verified
  completion distinct from action failure, bounded recovery
  (per-step retries, re-targeting, run-level recovery budgets), and startup
  reconciliation of interrupted runs.
- **Unsupported desktop actions fail safely** via an application allowlist.
- **ActionPilot Playground:** deterministic local-only scenarios
  (`playground-site/`, `docs/PLAYGROUND.md`) exercising the full
  observe→decide→act→verify→recover→approve loop without AI, cloud, or
  external sites.
- **Security hardening:** approval records no longer store typed form values;
  audit records redact secret-looking text (`password=...` → `[redacted]`);
  browser session ids are validated before any filesystem use.
- **Configuration:** the repo-root `.env` is loaded at startup (shell
  environment wins); `.env.example` documents only variables the code reads.
- **CI:** GitHub Actions running the backend suite on Windows and the frontend
  typecheck/build on Linux for every push and pull request.
- **Documentation:** refreshed README, plus CONTRIBUTING, SECURITY,
  ARCHITECTURE, this changelog, and GitHub issue/PR templates.

### Fixed

- Runs interrupted by a crash are reconciled to a terminal state on startup
  instead of appearing stuck.
- Video streaming honors HTTP `Range` requests and answers empty recordings
  with an empty 200 (never 416).

### Known limitations

- Windows is the only verified backend platform (pywinauto/pywin32 pins); the
  frontend has no hard Windows dependency.
- No authentication: the API trusts every local process on `127.0.0.1`.
- No retention automation for runs, screenshots, or video.
- Chromium-based recording/replay only; no CAPTCHA or bot-check bypass; one
  replay run at a time; no conditional logic inside Skills; no scheduler.
- Gmail, web research, desktop control, memory, and routines are experimental
  and outside the verified workflow.
