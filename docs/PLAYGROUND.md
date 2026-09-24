# ActionPilot Playground

A small, deterministic, local-only proving ground for the adaptive execution
architecture: **Teach → Observe → Decide → Act → Verify → Recover → Approve → Report**.

## What it is and why it exists

`playground-site/` is a static page of synthetic UI scenarios with explicit
state machines (no randomness, no network, no dependencies). A thin local
driver, `backend/app/services/agent/playground_tool.py`, drives those pages
through the **existing** agent loop, so every adaptive seam runs against
realistic changing UI states:

```
observe → decide → runtime risk → act → observe again → verify
        → recover/re-target if needed → approval when required
        → completed / failed with evidence
```

It exists to prove the architecture, not to become a second product. The tool
driver is one file and easy to delete; it is **not** registered in the
production tool registry.

## How to start it

Automated tests serve the site themselves on an ephemeral port — nothing to
start. To browse manually:

```
python -m http.server 4174 --directory playground-site
```

then open the local address it prints (typically `http://127.0.0.1:4174/`).

- Start a scenario: open `playground.html?scenario=<name>` (the index lists all).
- Reset: reload the page, click "Reset scenario", or call `__playground.reset()`.
- Inspect: read `window.__playground.state` (or the rendered state panel).
- Mutate (deterministic whitelist only): `window.__playground.mutate("stale-target")`
  — only meaningful on the `target-change` scenario before it advances.

That JS object is the entire control surface; there is deliberately no new API
endpoint or long-running server.

## Scenarios and what each proves

| Scenario (`?scenario=`) | Proves |
| --- | --- |
| `normal` | Happy path: observe → fill (read-back checks) → submit → verify, with screenshot evidence per step. |
| `target-change` | A taught target grows stale; a fresh observation produces one deterministic re-target (`MAX_RETARGETS == 1`), no fuzzy matching. |
| `verify-delay` | The action succeeds while the outcome is still "Saving…"; verification is a distinct phase that re-observes exactly once (bounded `wait_for`) and then passes — or fails honestly and stops when the transition never arrives. |
| `recovery` | First attempt fails → bounded recovery decisions (`retry_after_delay`, `replan`) → fresh observation finds the alternate control → retry succeeds. Uses the existing per-step budget of 2. |
| `approval` | `Send application` is escalated by runtime risk from the fresh observation (`low → high`), the run stops at the existing approval gate, then approve-and-execute-with-verification or deny-and-stop-safely. |
| `failure` | Recovery cannot succeed: exactly 1 initial + 2 bounded retries, then `stop`; the run-global cap of 5 is enforced across steps; the run ends failed with structured error/evidence. |

## Running the tests

```
cd backend
python -m pytest -q                       # full suite (baseline + playground)
python -m pytest tests/test_playground.py -q   # playground only
```

Tests use deterministic page states and Playwright's own bounded waits — no
arbitrary sleeps, no screenshot assertions, no timing-sensitive polling.

## Bounds

- Runs on the **existing** budgets, unchanged: `IDEMPOTENT_STEP_RETRIES = 2`,
  `RUN_RECOVERY_ATTEMPTS = 5`, `MAX_RETARGETS = 1`.
- The only production-code change is one classification line in
  `agent/loop.py`: `tool == "playground"` steps are retry-eligible like other
  local read-only/idempotent steps (high-risk steps still never auto-retry).
- All waits in the driver are hard-capped (`ACTION_TIMEOUT_MS`,
  `MAX_WAIT_TIMEOUT_MS`); there are no `while True` loops or unbounded polls.
- Local-only: the driver refuses non-local URLs.

## What it intentionally does NOT test

- Recorder, replay engine, locator architecture, run state machine, approval
  infrastructure internals (those have their own suites — the playground only
  *consumes* them).
- The protected demo contract (`demo-site/account.html`, Form Regression Test
  skill) — the playground never touches them; a test guards that separation.
- LLM/AI, cloud APIs, vision, scheduling, Gmail/real accounts, third-party
  websites, CAPTCHA, payments, real deletions, or destructive desktop actions.
- Production frontend behavior or API endpoints (no backend endpoint was added).
