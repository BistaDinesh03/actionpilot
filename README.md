# ActionPilot

**Teach it once. Let it do the work.**

ActionPilot is a local-first automation MVP. It stores reusable skills in SQLite, matches natural-language commands deterministically, extracts explicit variables, and keeps review and approval in the user's hands.

## Current MVP

- React + Vite command center with Skills, Teach, Runs, Connections, and Settings surfaces.
- FastAPI + SQLite health check, skill CRUD, command matching, run creation, and audit records.
- Real Chrome Manifest V3 teaching recorder with normalized target metadata.
- Safe teaching flow with password, token, payment, and secret-field filtering.
- Reviewable live timeline and SQLite-backed Skills.
- Local demo shop with search, product detail, variant selection, and cart.
- Natural-language skill matching with confidence, ambiguity handling, variable extraction, and plan preview.

Gmail OAuth and desktop automation are intentionally staged next. Playwright replay and the focused natural-language agent are available without an AI key.

## Setup on Windows

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
cd frontend
npm install
```

Run the API in one PowerShell terminal:

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

Run the frontend in another:

```powershell
cd frontend
npm run dev
```

Open http://localhost:5173.

Run the demo shop in a third PowerShell terminal:

```powershell
.\scripts\demo.ps1
```

Load the extension in Chrome:

1. Run `cd extension; npm install; npm run build`.
2. Open `chrome://extensions`.
3. Enable **Developer mode**.
4. Choose **Load unpacked**.
5. Select the repository `extension` folder.
6. Pin **ActionPilot Recorder** if desired.

Teaching acceptance flow:

1. Open `http://localhost:5173` and click **Teach a new task**.
2. Name it `Demo Keyboard Search`, then start teaching.
3. Open `http://127.0.0.1:4173`, search `keyboard`, open the product, select a variant, and add it to cart.
4. Return to ActionPilot, stop teaching, review the live steps, and save the Skill.
5. Open **Skills** and verify the recorded actions and domain are present.

## Run your first skill

Teach a workflow, save it, then choose **Run skill** from the Command or Skills view. ActionPilot creates a run, opens a local Chromium session with Playwright, executes each recorded action in order, and polls the run screen for progress. Use **Pause**, **Resume**, or **Stop** at any time. Failed actions stop the run and save a diagnostic screenshot under `runtime\runs\<run-id>`.

For the local demo:

```powershell
.\scripts\dev.ps1
.\scripts\demo.ps1
```

Then teach the demo shop workflow and run it from **Skills**. The first real replay requires Chromium once:

```powershell
python -m playwright install chromium
```

## Environment

Copy `.env.example` to `.env`. `AI_API_KEY`, `AI_BASE_URL`, and `AI_MODEL` are optional. Deterministic matching works without them. When configured, the optional OpenAI-compatible provider may return validated intent JSON only; it cannot execute code or bypass the existing executor and safety checks. Never commit `.env`, OAuth tokens, browser profiles, or the SQLite database.

## Natural-language commands

The command box normalizes a request, scores saved Skills by name, description, domain, and action metadata, extracts explicit variables, previews the plan, and sends approved work through the existing Playwright executor. For example:

```text
Run my keyboard workflow for a mouse
Run Demo Keyboard Search with product = white keyboard
```

If multiple Skills are equally plausible, ActionPilot asks which Skill to run instead of guessing. It is a focused personal automation agent, not an unrestricted general computer agent.

## Gmail setup

Gmail is optional and requires a Google Cloud project:

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/).
2. Enable **Gmail API** for the project.
3. Configure the OAuth consent screen. For personal use, External testing mode is sufficient; add your Google account as a test user.
4. Create an OAuth client under **APIs & Services > Credentials**. Use a Web application client and add `http://localhost:8000/api/gmail/callback` as an authorized redirect URI.
5. Copy the client ID, client secret, and redirect URI into `.env`:

```powershell
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://localhost:8000/api/gmail/callback
```

6. Start ActionPilot and open **Connections > Connect Gmail**. Google handles the login and consent screen; ActionPilot never receives or stores a Gmail password.

The requested scopes are `gmail.readonly`, `gmail.compose`, `gmail.send`, and `gmail.modify`. OAuth tokens are stored only in the ignored local `runtime\gmail\token.json` file and are never returned to the frontend or written to audit logs. Email commands create a draft preview and always require an explicit **Send email** approval. Automated tests use a mocked Gmail API and do not require Google credentials.

## Agent core and tools

The command box is routed through a typed tool registry. The deterministic fallback selects:

- `skill` for saved browser workflows, using the existing Playwright executor.
- `gmail` for drafts, replies, and approved sends, using the existing Gmail service.
- `web_research` for read-only public web search, visible text extraction, source collection, comparison, and content ideas.

Agent plans are validated with Pydantic before execution. Research uses Playwright against public search results and returns cited titles and URLs. Mixed requests run research first, then stop before Gmail sending until the user explicitly approves. No tool accepts Python, PowerShell, shell commands, arbitrary Playwright code, or arbitrary Gmail instructions from an LLM.

## Windows Desktop Control

DesktopTool uses `pywinauto` with the Windows UI Automation backend and is registered alongside SkillTool, GmailTool, WebResearchTool, and BrowserTool. The initial application allowlist contains `notepad`, `explorer`, `chrome`, and `vscode`; application plans use these IDs rather than executable strings. Set `VSCODE_PATH` when the default `Code.exe` lookup is not available.

Supported desktop actions are launch, focus, semantic click/double-click, ordinary text entry, key/hotkey input, scroll, wait, and screenshot. Observations are bounded to visible window/control metadata and a runtime screenshot. Text entry never records passwords, and runtime screenshots are excluded by `.gitignore`.

High-risk desktop requests such as deletion, installers, system/security changes, publishing, or sending stop for explicit approval. The tool never accepts PowerShell, `cmd.exe`, Python, arbitrary shell commands, credential-store access, keylogging, or security bypass instructions. Desktop UI Automation may require an unlocked interactive Windows session; localized application titles are matched by stable UI Automation metadata where possible.

## Unified visual computer use

Browser and Windows observations are normalized through `ComputerObservation`, and proposed actions are validated as `ComputerAction` objects before reaching the existing BrowserTool or DesktopTool authorities. Semantic browser/UI Automation metadata is preferred; screenshots are bounded runtime artifacts and optional visual-model input. Visual targets require a confidence threshold and never bypass high-risk approval.

The AgentLoop is bounded by `MAX_AGENT_STEPS` and recovery attempts. It can observe tool results, append validated next steps, retry recoverable failures, pause, stop, and wait for approval. The optional vision provider remains disabled without AI configuration; the semantic path works without a vision model.

## Agent loop, memory, and routines

Agent runs use a bounded Observe -> Plan -> Risk Check -> Act -> Observe loop. `MAX_AGENT_STEPS` defaults to `15`; risky steps stop in `waiting_confirmation`, and stop/pause controls remain available through the existing Run system. Agent state includes the goal, plan, observations, variables, tool history, result, and status.

Explicit preferences can be saved under **Memory** and are included in later agent results when relevant. **Routines** store a name, prompt, schedule, and enabled state; **Run now** invokes the same Agent Loop and never bypasses Gmail or other high-risk approval gates. Memory is intentionally small SQLite CRUD, not a vector database or silent personal profile.

Useful agent endpoints:

```text
POST /api/agent/run
GET  /api/agent/runs/{id}
POST /api/agent/runs/{id}/pause
POST /api/agent/runs/{id}/resume
POST /api/agent/runs/{id}/stop
GET/POST/PUT/DELETE /api/memory
GET/POST/PUT/DELETE /api/routines
POST /api/routines/{id}/run
```

## Security boundary

ActionPilot is not an unrestricted agent. The planned execution layer must use an allowlist, bounded retries, emergency stop, secret-field filtering, and explicit approval for high-risk actions such as sending, purchasing, deleting, or publishing.

## Development checks

```powershell
python -m py_compile backend\app\main.py
cd frontend
npm run build
```

## Roadmap

1. Chrome MV3 recorder and local bridge.
2. Playwright execution engine with locator priority and screenshots on failure.
3. Real run state machine with pause, resume, stop, and approval gates.
4. Gmail OAuth draft/send flow.
5. Local demo shop and end-to-end automation tests.
