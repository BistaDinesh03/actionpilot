# ActionPilot — User Guide

**Record a browser workflow. Replay it locally.**

ActionPilot is a local-first browser automation tool. You record a workflow
once, save it as a reusable **Skill**, and replay it later — with the same data
or with different values.

Everything runs on your machine. No account, no cloud. Skills, runs,
screenshots, and video are stored in the project folder.

---

## What you can do today

- Record a browser workflow in Chrome or Brave.
- Save it as a reusable Skill.
- Replay it in Chromium (headless or visible) with pause/resume/stop.
- Fill in variable values at run time using placeholders like `{{name}}`.
- Watch the run: per-step screenshots, a full video, and a step timeline.
- Click any step to see its screenshot and jump the video to that moment.
- Add wait and assert steps to Skills for reliability.
- Export any Skill as a runnable Playwright test (`.spec.ts`).

---

## Prerequisites

- Windows
- Python 3.11
- Node.js (for the frontend and the extension build)
- Chrome or Brave

---

## 1. Install and start

### One-time install

Run these from the project root:

    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r backend/requirements.txt
    cd frontend; npm install; cd ..
    cd extension; npm install; npm run build; cd ..

### Start the API and the frontend

    .\scripts\dev.ps1

That opens two PowerShell windows: the FastAPI backend on
<http://127.0.0.1:8000> and the Vite frontend on <http://localhost:5173>.

### Load the browser extension

1. Open `brave://extensions` (or `chrome://extensions`).
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked**.
4. Select the `extension` folder inside the ActionPilot project.
5. Pin **ActionPilot** to the toolbar.

If the extension popup shows **Ready to teach**, you are ready.

### Optional: start the demo shop

A small local shop site is included for testing:

    .\scripts\demo.ps1

It runs at <http://127.0.0.1:4173>.

---

## 2. Record your first Skill

1. Open <http://localhost:5173> and click **Teach** in the sidebar.
2. Type a task name (for example `demo-test-1`) and click **Start teaching**.
3. The browser enters recording mode. Open a new tab and navigate to the page
   you want to automate.
4. Perform the workflow slowly: click the Contact link, fill each field, click
   Send.
5. Click the **ActionPilot** icon in the toolbar and click
   **Stop teaching & save**.
6. A review modal opens in ActionPilot. Confirm the steps and click
   **Save skill**.

You can also start a recording directly from the extension popup.

Recording tips:

- Start each recording from a blank tab, then navigate to the site. This makes
  the first step a navigate step, so the Skill knows which URL to open.
- Only click real interactive elements: buttons, links, inputs, checkboxes,
  selects. Clicking empty page backgrounds can be recorded as noise.
- After typing in a field, check the value. If it is wrong, delete and retype.
- Password fields, tokens, and secrets are skipped automatically.

---

## 3. Replay a Skill

1. Open **Skills** in the sidebar.
2. Find the Skill you want to run and click **Run**.

If the Skill contains placeholders like `{{name}}`, a **Run with variables**
modal appears first. Fill in the values and click **Run skill**.

The app switches to the **Runs** page and shows the run in progress.

---

## 4. Use variables

Variables make a Skill reusable with different data.

To author a variable, type the placeholder **literally** into a form field
**during recording**:

- Name field   → `{{name}}`
- Email field  → `{{email}}`
- Message field → `{{message}}`

The braces are required. On a US keyboard, `{` is Shift+[ and `}` is Shift+].

When you later click **Run**, ActionPilot detects the placeholders and asks you
for values. The executor replaces `{{name}}` with the value you typed before
the browser runs the step.

The values you provide are stored on the run record and visible in
`GET /api/runs/{id}`.

---

## 5. Run Details: screenshots, video, step timeline

When a run starts, the **Runs** page shows:

- Left column: the step list with status per step.
- Right column: the run video (once finished) and the current step's
  screenshot.

Click any step in the list to:

- Highlight it.
- Show its screenshot below the video.
- Seek the video to that step's timestamp.
- Show its action type, URL, and title.

Failed steps are highlighted red and their exact error is shown. A failed run
opens with the failed step pre-selected.

Every run's screenshots and video are saved on disk under:

    runtime/runs/<run-id>/
      step-0.png
      step-1.png
      ...
      video/<timestamp>.webm

---

## 6. Wait and assert steps

Two step types exist beyond the standard clicks and typing:

- **wait** — pause until a target becomes visible, up to N milliseconds. If the
  target has no selector, wait behaves as a fixed timeout (`value` = ms).
- **assert** — verify a target is visible. If it is not visible within N ms,
  the run fails with a clear message naming the step and the reason.

There is **no UI yet** to add these interactively. Author them by editing the
Skill JSON via `PUT /api/skills/{id}`. Example assert step:

    {
      "type": "assert",
      "label": "Submit button visible",
      "value": "5000",
      "risk_level": "low",
      "target": { "role": "button", "text": "Send Message", "css": "#submitBtn" }
    }

When an assert fails, the run status becomes `failed` and the error is:

    AssertionError: assert step failed: target is not visible within 3000ms
    (Could not find a visible element using the recorded target)

Both wait and assert are non-mutating and are always marked low-risk.

---

## 7. Export a Playwright test

Every Skill can be exported as a standalone Playwright `.spec.ts` file.

1. Open **Skills**.
2. Find the Skill and click **Playwright**.

Your browser downloads `<skill-name>.spec.ts`.

Run it standalone:

    npx playwright test <skill-name>.spec.ts --project=chromium

The exported file uses real Playwright APIs — `page.goto`, `page.getByRole`,
`page.getByLabel`, `page.locator(...).fill(...)`,
`await expect(...).toBeVisible()` — and runs in a fresh browser, not inside
ActionPilot.

Placeholders like `{{name}}` are preserved as-is in the export, so you can
substitute them with environment variables or test fixtures on your side.

---

## 8. Example workflows to try

### A. Fill a contact form with variables

1. Record: navigate to a site with a contact form, click into Name / Email /
   Message, type `{{name}}`, `{{email}}`, `{{message}}`, click Send. Stop and
   save as `contact-demo`.
2. Run it: **Skills → Run**. Fill in real values in the modal.
3. Check the Run Details. The screenshots show the substituted values.

### B. Record → export → run in CI

1. Record a simple login flow or a form submission.
2. Click **Playwright** to download the `.spec.ts`.
3. Copy it into any Playwright project and run `npx playwright test`.

### C. Replay the same Skill twice with different values

1. Record a Skill with `{{name}}` in a field.
2. Run it with Alice. Wait for completion.
3. Run it again with Bob. Both runs are visible in the **Runs** list with their
   own screenshots and video.

---

## 9. Current limitations

- No UI to author wait and assert steps. You edit the Skill JSON.
- No conditional logic (if / else).
- No CAPTCHA handling. Sites behind Cloudflare or reCAPTCHA may not complete.
- Chromium-based recording (Chrome/Brave) and Playwright Chromium replay only.
- Local-only. No cloud sync, no accounts, no sharing.
- One browser run at a time.
- Recorded selectors are captured from the live DOM. Very dynamic sites may
  drift and need re-recording.
- Skill import/export as JSON is not yet built (Playwright test export works).
- No scheduler. Runs start when you click Run.

---

## 10. Troubleshooting

**Popup says "Checking connection..." forever**

- The backend is not running. Start it with `.\scripts\dev.ps1`.
- Check that <http://127.0.0.1:8000/health> returns `{"status":"ok"}`.

**Skill saved but has 0 steps**

- You recorded without performing any actions. Start a fresh recording,
  navigate to the site while recording, and perform the workflow.

**Run fails on the very first step**

- The Skill may be missing a navigate step. Start recordings from a blank tab
  and navigate to the site while recording.

**Assert failed**

- The target was not visible within the timeout. Check the step's target object
  and increase `value` (milliseconds) if the page is slow.

**Screenshot not available in Run Details**

- The step did not produce a screenshot yet. Click **Retry load**.

---

## 11. Where things live on disk

- `actionpilot.db` — SQLite database (Skills, Runs, Memory, Routines, Audit
  log).
- `runtime/runs/<run-id>/` — per-run screenshots (`step-N.png`) and video
  (`video/*.webm`).
- `extension/` — the browser extension source and `dist/` build output.
- `frontend/` — the React + Vite UI.
- `backend/` — the FastAPI server and Playwright executor.
- `scripts/dev.ps1` — start backend and frontend.
- `scripts/demo.ps1` — start the demo shop.

---

If something behaves differently from this guide, the guide is wrong, not the
code. Open an issue or check the source.
