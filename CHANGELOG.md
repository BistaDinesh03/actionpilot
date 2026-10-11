# Changelog

All notable changes to ActionPilot are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
