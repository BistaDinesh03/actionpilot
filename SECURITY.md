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
- Audit and approval records **redact** secret-looking text (`password=...`
  becomes `[redacted]`), and approval records never store typed form values.
- High-risk actions require an explicit human approval; rejection stops the
  run. Unsupported destructive desktop actions fail safely by allowlist.
- Optional Gmail support stores its OAuth refresh token **in plaintext** at
  `runtime/gmail/token.json` (git-ignored). Disable it if that is unacceptable
  on your machine.

## Data at rest

Everything ActionPilot stores stays on your machine: `actionpilot.db`
(Skills, runs, audit logs, memories), `runtime/runs/` (screenshots, video),
`runtime/gmail/` (OAuth token). There is no built-in retention automation —
to remove your data, stop the app and delete those files.
