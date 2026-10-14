# ActionPilot Architecture

This describes the system as it exists today: components, trust boundaries,
the execution loop, approvals, bounded recovery, and local storage. It is a
map of the current code, not a roadmap.

## Components

```text
┌──────────────┐   browser actions   ┌───────────────────────┐   steps   ┌──────────────────┐
│ MV3 extension│ ──────────────────▶ │ FastAPI backend :8000 │ ────────▶ │ Playwright       │
│ (recorder)   │                     │ SQLite: actionpilot.db│           │ executor/runtime │
└──────────────┘                     └───────────▲───────────┘           └──────────────────┘
                                     │ React UI :5173        │
                                     └───────────────────────┘
```

- **`extension/`** — Manifest V3 recorder (TypeScript). Captures normalized
  browser actions, filters sensitive inputs client-side, posts to the local
  API.
- **`frontend/`** — React + Vite UI (served by Vite on `localhost:5173`).
  Talks only to `127.0.0.1:8000`.
- **`backend/`** — FastAPI app (`app/main.py`) with SQLite storage, the
  browser executor (`app/services/execution/`), and the agent loop
  (`app/services/agent/`).
- **`demo-site/`, `agent-test-site/`, `playground-site/`** — static local
  pages used by users (practice) and by tests (E2E and adaptive-execution
  scenarios). No test ever touches an external site.

## Trust boundaries

- **Network:** uvicorn binds `127.0.0.1` (default; no `--host` anywhere).
  CORS allows only the local dev origin. There is **no authentication** —
  every local process is trusted. The port must never be exposed.
- **URL policy:** agent browser tools only navigate to `LOCAL_HOSTS`
  (127.0.0.1/localhost) for the account demo; session ids are validated
  (`[A-Za-z0-9_-]{1,64}`) before any runtime filesystem use.
- **Desktop allowlist:** only `notepad`, `explorer`, `chrome`, `vscode`
  (path overridable via `VSCODE_PATH`) can be launched; anything else fails
  safely. High-risk words (delete, installer, system setting, security,
  publish, send, purchase) force risk=high regardless of tool.
- **Input handling:** every request body is a pydantic model; SQL is
  parameterized; there is no `eval`/`exec`/`pickle`/`yaml.load`; file uploads
  are not accepted. The recorder and the agent observer never read input field
  values (password/token/secret fields are dropped at capture time).
- **Evidence redaction:** `write_audit` masks secret-looking `key=value`
  assignments before persisting; approval records are stripped of typed
  `value` fields (`sanitize_approval_detail`); `run_steps` never store typed
  values at all.

## Run state machine

States: `queued`, `running`, `paused`, `waiting_confirmation`, `completed`,
`failed`, `stopped`. Transitions are validated centrally
(`app/services/execution/run_state.py`); illegal transitions raise
`InvalidTransition`, same-state writes are idempotent no-ops. Terminal states
are immutable except for identical rewrites.

**Startup reconciliation:** runs left non-terminal by a crash are moved to a
terminal state and audited (`run_interrupted`) so the UI never shows a run
that cannot move again.

## Agent execution loop

`app/services/agent/loop.py` executes a plan **re-planned server-side** (the
client's plan is never trusted for parameters):

1. **Observe** — bounded, read-only page observation before any action;
   visible text is truncated; input values are never read.
2. **Decide** — the current step is executed through its tool; re-targeting a
   moved element is bounded (`MAX_RETARGETS = 1`).
3. **Runtime risk** — risk is classified at execution time (plan risk plus
   high-risk vocabulary), not taken from the client.
4. **Act** — the tool performs the step.
5. **Verify** — the step's effect is checked; **success is reported only when
   verification passes**. Action failures and verification failures are
   distinct, separately audited outcomes.
6. **Recover** — failures are classified (`app/services/agent/recovery.py`):
   only idempotent steps retry (`IDEMPOTENT_STEP_RETRIES = 2`), run-level
   recovery is capped (`RUN_RECOVERY_ATTEMPTS = 5`), delays are short
   (`RETRY_DELAY_SECONDS = 0.25`, max 5 s) and stop-interruptible. High-risk
   steps never auto-retry.
7. **Report** — the run's state, per-step outcomes, and audit trail are
   persisted and shown in the UI.

The whole loop is bounded by `MAX_AGENT_STEPS` (default 15) and honors the
pause/stop controls at every step boundary.

## Approval behavior

The approval gate (`approval_gate` in `app/main.py`) is authoritative: a
high-risk step blocks inside the executor until its approval row is resolved.
Approve resumes the run; reject stops it with "Approval rejected"; the stop
control interrupts the wait. An **upfront** approval covers the first
high-risk step of an entire run so users decide once, not per step. Nothing
in the codebase can bypass the gate for a step classified high-risk, and the
stored approval evidence contains no typed values.

## Local storage

| Location | Contents |
| --- | --- |
| `actionpilot.db` | `skills` (recorded steps incl. recorded values), `runs` (plan, variables, status, output), `run_steps` (labels, outcomes, verification, screenshot paths — no typed values), `approvals`, `audit_logs` (redacted), `memories`, `routines` |
| `runtime/runs/<run-id>/` | per-step screenshots, session video |
| `runtime/gmail/token.json` | optional Google OAuth refresh token (plaintext, git-ignored) |
| `runtime/desktop/`, `runtime/browser/` | desktop/browser run artifacts |

Everything is git-ignored; nothing leaves the machine. There is no retention
automation — deletion is manual.

## Non-goals (by design)

- **No LLM or AI traffic.** An OpenAI-compatible provider class exists but is
  not wired into any route; planning is deterministic matching + templates.
- **No cloud, accounts, telemetry, or scheduling.**
- **No vision models** — observation uses the accessibility/DOM tree.
- **No universal automation claim.** Chromium only; CAPTCHA/bot checks are out
  of scope; heavily dynamic sites may need re-recording.

## Testing map

- `backend/tests/` — 204 tests: unit (state machine, matcher, recovery
  classification, redaction, security hardening), API (TestClient), and
  local-browser E2E against
  `demo-site/`/`agent-test-site/` (replay, verification, approvals, adaptive
  loop, playground scenarios). Run: `python -m pytest -q`.
- `frontend/` — `npm test` (tsc typecheck) and `npm run build`.
- CI: `.github/workflows/ci.yml` — backend on `windows-latest` (pywinauto is
  Windows-only), frontend on `ubuntu-latest`.
- The **playground** (`docs/PLAYGROUND.md`) exists to exercise the adaptive
  seams deterministically without touching production/demo flows.
