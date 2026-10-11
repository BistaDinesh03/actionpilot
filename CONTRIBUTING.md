# Contributing to ActionPilot

Thanks for helping. ActionPilot is a local-first tool: contributions should
keep it that way.

## Ground rules

- **Local-only.** No cloud services, accounts, telemetry, LLM calls, or
  external sites in code paths or tests. Tests must run offline against
  `demo-site/`, `agent-test-site/`, or `playground-site/`.
- **Bounded everything.** No unbounded loops, polling, or sleeps. Every retry,
  re-target, and recovery path must have a hard budget, and budgets must stay
  at or below their current values unless a change is explicitly justified.
- **Safety boundaries are not negotiable.** The approval gate is authoritative
  for high-risk actions, denial must stop the run, unsupported destructive
  actions must fail safely, and success is never reported without verification.
- **No secrets or user data** in commits, tests, screenshots, or issues.

## Development setup

Prerequisites: Windows, Python 3.11, Node.js. See the
[README Quick Start](README.md#quick-start) for install and startup commands.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt
python -m playwright install chromium   # first time only
cd frontend; npm install; cd ..
```

Start the app with `.\scripts\dev.ps1` (backend on <http://127.0.0.1:8000>,
frontend on <http://localhost:5173>) and the demo shop with `.\scripts\demo.ps1`.

## Tests

Run these before opening a PR:

```powershell
cd backend; python -m pytest -q     # full backend suite (unit + local E2E)
cd frontend; npm test; npm run build # typecheck + production build
```

- Investigate failures; do not weaken or delete assertions to get green.
- New behavior needs a regression test. Timing-sensitive tests must be
  deterministic (bounded waits on real conditions, no arbitrary sleeps).
- The demo contract is pinned by tests: do not change `demo-site/account.html`
  behavior that existing tests rely on.

## Conventions

- Python: FastAPI + pydantic models for every request body; SQLite through the
  existing `db()` context manager; keep functions small and explicit.
- TypeScript/React: no `dangerouslySetInnerHTML`; keep the API base URL and
  call shapes in `frontend/src/lib/api.ts`.
- Vocabulary: Skills, Runs, Steps, Approvals, the run state machine
  (queued → running → paused / waiting_confirmation → completed / failed /
  stopped). Preserve it.
- Commit style: one coherent change per commit, imperative subject
  (`fix: ...`, `feat: ...`, `test: ...`, `docs: ...`).

## Pull requests

1. Branch from `main`; keep the diff focused — no formatting-only hunks, no
   unrelated files, never commit `test-results/`, `runtime/`, `*.db`, or
   `.env`.
2. Fill in the PR template: what/why, the exact commands you ran with their
   pass/fail counts, and safety notes if you touched execution, approvals,
   recovery, or the demo contract.
3. CI must be green (backend on Windows, frontend typecheck/build).
4. Expect review questions about safety boundaries — that is the point.

## Scope

ActionPilot deliberately does **not** claim universal automation support and
does not include scheduling, cloud sync, vision models, or unrestricted
computer control. Feature ideas that need those should first propose a
local-first alternative (see the feature-request template).
