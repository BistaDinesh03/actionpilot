# Security Policy

## Supported versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a vulnerability

Please report security issues **privately**, using
[GitHub Security Advisories](https://github.com/BistaDinesh03/actionpilot/security/advisories)
("Report a vulnerability") on this repository. Do not open a public issue for
an exploitable vulnerability.

Include:

- the affected component and commit/version;
- steps to reproduce using only local, synthetic data;
- the impact you observed.

We will acknowledge the report when it is seen and discuss next steps in the
advisory thread. This is a volunteer-maintained project with **no guaranteed
response time**; please do not publish details until a fix or mitigation is
agreed, or after a reasonable disclosure window.

Never include real credentials, tokens, personal data, or recordings from your
machine in a report — reproduce with the local demo/playground sites only.

## Threat model (local trust boundary)

ActionPilot is **local-first**: the API server binds to `127.0.0.1` (uvicorn's
default; nothing in this repository binds `0.0.0.0`) and the UI is served from
`localhost`. There is **no authentication** — by design, every process and user
on your machine can call the API, start runs, and approve actions. That is the
trust boundary:

- Do not port-forward, tunnel, or otherwise expose the backend to a network.
- The browser automation uses **fresh headless browser profiles** — never your
  personal browser profile, cookies, or logins.
- Sensitive recording is filtered at capture time: password, token, payment,
  and secret fields are never recorded (extension and backend both filter).
- Audit, approval, and run-title records **redact** secret-looking text
  (`password=...` becomes `[redacted]`), approval records never store typed
  form values, and failure messages are stored as a single bounded line
  (`ErrorType: message`) — never a stack trace.
- File-serving endpoints re-check every stored path against `runtime/` before
  opening it, so a poisoned database row cannot become an arbitrary file read.
- High-risk actions require an explicit human approval; rejection stops the
  run. Unsupported destructive desktop actions fail safely by allowlist.
- Optional Gmail support stores its OAuth refresh token **in plaintext** at
  `runtime/gmail/token.json` (git-ignored). Disable it if that is unacceptable
  on your machine.

### Accepted limitations (by design, not defects)

- **No authentication on localhost.** Any local process can call the API. This
  is a convenience trade-off, not a claim of safety against other local users
  or malware — see the trust boundary above.
- **Run records keep the original request text** in `runs.plan`. An approved
  run resumes by re-planning from that exact text, so it is stored verbatim.
  The displayed run title and the audit trail mask it.
- **Approvals and pauses wait indefinitely.** A paused run holds its thread
  until you decide or stop the app; there is no approval timeout.
- **The optional Gmail token file is plaintext**, and its OAuth endpoints use
  GET redirects as Google requires.
- **No retention automation.** Deletion is manual (stop the app, delete
  `actionpilot.db` and `runtime/`).

## Data at rest

Everything ActionPilot stores stays on your machine: `actionpilot.db`
(Skills, runs, audit logs, memories), `runtime/runs/` (screenshots, video),
`runtime/gmail/` (OAuth token). There is no built-in retention automation —
to remove your data, stop the app and delete those files.
