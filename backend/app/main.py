from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
import asyncio, sys
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .services.execution.executor import BrowserExecutor, ConfirmationRequired, ExecutionStopped
from .services.execution.run_state import RUN_STATUSES, TERMINAL_RUN_STATUSES, InvalidTransition, validate_transition
from .services.agent.agent import ActionPilotAgent
from .services.agent.loop import AgentLoop
from .services.agent.memory import MemoryStore
from .services.agent.models import AgentPlan, AgentRequest, PlanStep
from .services.agent.planner import calculate_risk
from .services.agent.registry import build_default_registry
from .services.agent.router import AgentRouter
from .services.agent.routine import RoutineStore
from .services.agent.state import AgentState
from .services.gmail.models import EmailDraft, EmailIntent, EmailSendRequest
from .services.gmail.service import GmailService, parse_email_command
from .services.matching.matcher import match_command

ROOT = Path(__file__).resolve().parents[2]
# Load the optional repo-root .env so the documented configuration actually
# works; variables already present in the shell environment always win.
load_dotenv(ROOT / ".env")
DB_PATH = ROOT / "actionpilot.db"
gmail_service = GmailService(ROOT)
agent_registry = build_default_registry(match_command, gmail_service, ROOT / "runtime" / "desktop")
actionpilot_agent = ActionPilotAgent(agent_registry, AgentRouter(agent_registry))
memory_store = MemoryStore(DB_PATH)
routine_store = RoutineStore(DB_PATH)
agent_loop = AgentLoop(actionpilot_agent, agent_registry, max_steps=int(os.getenv("MAX_AGENT_STEPS", "15")))

app = FastAPI(title="ActionPilot API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


app.mount("/guide", StaticFiles(directory=ROOT / "docs"), name="guide")


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def db() -> sqlite3.Connection:
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    with db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS skills (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                steps TEXT NOT NULL DEFAULT '[]',
                domains TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                last_run TEXT,
                runs INTEGER NOT NULL DEFAULT 0,
                success_rate REAL NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                skill_id TEXT,
                task_name TEXT NOT NULL,
                status TEXT NOT NULL,
                current_step INTEGER NOT NULL DEFAULT 0,
                logs TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS run_steps (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                step_index INTEGER NOT NULL,
                label TEXT,
                action_type TEXT,
                status TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                error TEXT,
                screenshot_path TEXT,
                url TEXT,
                title TEXT,
                verification TEXT
            );
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                step_index INTEGER NOT NULL DEFAULT 0,
                kind TEXT NOT NULL DEFAULT 'step',
                summary TEXT NOT NULL DEFAULT '',
                detail TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );
            CREATE TABLE IF NOT EXISTS audit_logs (
                id TEXT PRIMARY KEY,
                event TEXT NOT NULL,
                detail TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(runs)")}
        skill_columns = {row[1] for row in connection.execute("PRAGMA table_info(skills)")}
        for name, definition in {"tags": "TEXT NOT NULL DEFAULT '[]'", "capabilities": "TEXT NOT NULL DEFAULT '[]'", "usage_count": "INTEGER NOT NULL DEFAULT 0"}.items():
            if name not in skill_columns:
                connection.execute(f"ALTER TABLE skills ADD COLUMN {name} {definition}")
        for name, definition in {
            "current_action": "TEXT",
            "error": "TEXT",
            "screenshot_path": "TEXT",
            "variables": "TEXT NOT NULL DEFAULT '{}'",
            "tool": "TEXT",
            "plan": "TEXT NOT NULL DEFAULT '[]'",
            "output": "TEXT NOT NULL DEFAULT '{}'",
            "requires_confirmation": "INTEGER NOT NULL DEFAULT 0",
        }.items():
            if name not in columns:
                connection.execute(f"ALTER TABLE runs ADD COLUMN {name} {definition}")
        step_columns = {row[1] for row in connection.execute("PRAGMA table_info(run_steps)")}
        for name, definition in {"label": "TEXT", "action_type": "TEXT", "verification": "TEXT"}.items():
            if name not in step_columns:
                connection.execute(f"ALTER TABLE run_steps ADD COLUMN {name} {definition}")


@app.on_event("startup")
def startup() -> None:
    init_db()
    reconcile_interrupted_runs()


class Target(BaseModel):
    tag: str | None = None
    role: str | None = None
    name: str | None = None
    text: str | None = None
    label: str | None = None
    placeholder: str | None = None
    test_id: str | None = None
    css: str | None = None
    xpath: str | None = None


class Step(BaseModel):
    type: Literal["click", "type", "navigate", "select", "check", "uncheck", "press", "submit", "scroll", "wait", "assert"]
    label: str = Field(min_length=1, max_length=200)
    timestamp: str | None = None
    url: str | None = None
    title: str | None = None
    target: Target | None = None
    value: str | None = None
    risk_level: str = "low"


class SkillCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    steps: list[Step] = Field(default_factory=list, max_length=500)
    domains: list[str] = Field(default_factory=list, max_length=50)
    tags: list[str] = Field(default_factory=list, max_length=50)
    capabilities: list[str] = Field(default_factory=list, max_length=50)


class CommandRequest(BaseModel):
    command: str = Field(min_length=1, max_length=1000)
    execute: bool = False


class AgentExecuteRequest(BaseModel):
    plan: AgentPlan
    approved: bool = False


class MemoryRequest(BaseModel):
    type: str = Field(min_length=1, max_length=40)
    title: str = Field(min_length=1, max_length=160)
    value: str = Field(min_length=1, max_length=5000)


class RoutineRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    prompt: str = Field(min_length=1, max_length=4000)
    schedule: str = Field(default="manual", max_length=120)
    enabled: bool = True


class RunCreate(BaseModel):
    skill_id: str
    task_name: str | None = None
    variables: dict[str, str] = Field(default_factory=dict)


class TeachStart(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)


class TeachEvent(BaseModel):
    type: Literal["click", "type", "navigate", "select", "check", "uncheck", "press", "submit", "scroll", "wait", "assert"]
    label: str = Field(default="Browser action", max_length=200)
    timestamp: str | None = None
    url: str | None = Field(default=None, max_length=2000)
    title: str | None = Field(default=None, max_length=500)
    target: Target | None = None
    value: str | None = Field(default=None, max_length=500)
    input_type: str | None = Field(default=None, max_length=40)
    risk_level: str = "low"


def skill_from_row(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["steps"] = json.loads(item["steps"])
    item["domains"] = json.loads(item["domains"])
    item["tags"] = json.loads(item.get("tags") or "[]")
    item["capabilities"] = json.loads(item.get("capabilities") or "[]")
    return item


# Secret-looking assignments (`password=...`, `token: ...`) must never persist
# in audit evidence; the vocabulary mirrors is_sensitive_event below.
SENSITIVE_WORDS = r"(?:password|passwd|token|secret|api[_\- ]?key|access[_\- ]?key|credential)"
SENSITIVE_ASSIGNMENT = re.compile(rf"(?i)\b([\w\-]*{SENSITIVE_WORDS}[\w\-]*)([ \t]*[=:][ \t]*)([^\s,;]+)")
BEARER_TOKEN = re.compile(r"(?i)\b(bearer)([ \t]+)([^\s,;]+)")


def redact_audit_text(text: str) -> str:
    """Mask secret-looking text before it reaches the audit log.

    Commands and requests are stored as evidence of intent, so ordinary
    words stay readable while typed secrets become a fixed marker.
    """
    masked = SENSITIVE_ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", text)
    return BEARER_TOKEN.sub(lambda match: f"{match.group(1)}{match.group(2)}[redacted]", masked)


def write_audit(event: str, detail: str) -> None:
    with db() as connection:
        connection.execute(
            "INSERT INTO audit_logs VALUES (?, ?, ?, ?)",
            (str(uuid.uuid4()), event, redact_audit_text(detail)[:500], now()),
        )


def describe_error(error: BaseException) -> str:
    """A short, non-technical failure message safe to persist and serve.

    Full tracebacks embed absolute paths, interpreter frames and library
    versions and are returned unauthenticated by ``GET /api/runs/{id}``, so
    only the exception type and a bounded, redacted message are stored.
    """
    detail = redact_audit_text(f"{error}").strip()
    return f"{type(error).__name__}: {detail[:300]}"


def task_title(request_text: str) -> str:
    """Run title / approval fallback text: same masking as the audit log.

    ``runs.task_name`` is rendered in the UI, so it gets the same treatment
    as audit evidence. The operational copy in ``runs.plan`` stays verbatim
    because an approved run resumes by re-planning from that exact text.
    """
    return redact_audit_text(request_text)[:120]


# Local artifacts (screenshots, recordings, exports) live under this tree.
# Paths read back out of the database are re-checked against it before they
# are opened, so a poisoned row cannot become an arbitrary file read. Resolved
# on each call so tests that re-point ROOT keep working.
def contained_runtime_path(candidate: str | Path) -> Path | None:
    """Resolve ``candidate`` and return it only if it stays inside runtime/."""
    try:
        resolved = Path(candidate).resolve()
        runtime_root = (ROOT / "runtime").resolve()
    except (OSError, ValueError):
        return None
    if not resolved.is_relative_to(runtime_root):
        return None
    return resolved


teach_sessions: dict[str, dict[str, Any]] = {}


def is_sensitive_event(event: TeachEvent) -> bool:
    sensitive_words = ("password", "token", "secret", "api key", "credit card", "security code")
    target_text = event.target.model_dump_json() if event.target else ""
    haystack = f"{event.label} {target_text} {event.input_type or ''}".lower()
    return event.input_type == "password" or any(word in haystack for word in sensitive_words)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "actionpilot-api"}


@app.get("/api/connections")
def connections() -> dict[str, Any]:
    return {"gmail": {"status": gmail_service.status()}}


@app.get("/api/gmail/status")
def gmail_status() -> dict[str, str]:
    return {"status": gmail_service.status()}


@app.get("/api/gmail/connect")
def gmail_connect() -> RedirectResponse:
    try:
        return RedirectResponse(gmail_service.connect_url())
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@app.get("/api/gmail/callback")
def gmail_callback(code: str | None = None, state: str | None = None, error: str | None = None) -> RedirectResponse:
    if error or not code:
        return RedirectResponse("http://localhost:5173/?gmail=cancelled")
    try:
        gmail_service.complete_connection(code, state)
        return RedirectResponse("http://localhost:5173/?gmail=connected")
    except (RuntimeError, ValueError):
        return RedirectResponse("http://localhost:5173/?gmail=error")


@app.post("/api/gmail/disconnect")
def gmail_disconnect() -> dict[str, str]:
    gmail_service.disconnect()
    return {"status": "not_connected"}


def redacted_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}" if domain else "redacted"


def create_email_run(task_name: str, status: str, detail: str) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    created = now()
    with db() as connection:
        connection.execute("INSERT INTO runs (id, skill_id, task_name, status, current_step, logs, created_at, variables, current_action, tool, plan, output) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (run_id, None, task_name, status, 3, json.dumps([detail]), created, "{}", detail, "gmail", json.dumps([]), json.dumps({})))
        for index, label in enumerate(("Resolve recipient", "Prepare email", "Send email")):
            connection.execute("INSERT INTO run_steps (id, run_id, step_index, label, action_type, status, started_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), run_id, index, label, "email", "completed", created, created))
    return get_run_or_404(run_id)


def first_high_risk_index(plan: AgentPlan) -> int:
    """0-based index of the first step that requires approval (falls back to the first step)."""
    for index, step in enumerate(plan.steps):
        if step.risk == "high":
            return index
    return 0


def create_agent_run(plan: AgentPlan, status: str, output: dict[str, Any]) -> dict[str, Any]:
    run_id = str(uuid.uuid4())
    created = now()
    # Waiting runs rest on their approval step; finished runs on the last step.
    current_step = first_high_risk_index(plan) if status == "waiting_confirmation" else len(plan.steps)
    with db() as connection:
        connection.execute("INSERT INTO runs (id, skill_id, task_name, status, current_step, logs, created_at, variables, current_action, tool, plan, output, requires_confirmation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (run_id, None, task_title(plan.request), status, current_step, json.dumps([step.action for step in plan.steps]), created, json.dumps(plan.variables), "Complete" if status == "completed" else "Waiting for approval", plan.steps[0].tool if plan.steps else None, plan.model_dump_json(), json.dumps(output), int(plan.requires_confirmation)))
        for index, step in enumerate(plan.steps):
            connection.execute("INSERT INTO run_steps (id, run_id, step_index, label, action_type, status, started_at, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), run_id, index, step.action, step.tool, "completed" if status == "completed" else "waiting_confirmation", created, created if status == "completed" else None))
    return get_run_or_404(run_id)


@app.get("/api/gmail/profile")
def gmail_profile() -> dict[str, Any]:
    try:
        return gmail_service.profile()
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@app.get("/api/gmail/search")
def gmail_search(query: str) -> dict[str, Any]:
    try:
        return {"messages": [message.model_dump() for message in gmail_service.recent_messages(query)]}
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error


@app.post("/api/gmail/draft")
def gmail_draft(payload: EmailDraft) -> dict[str, Any]:
    try:
        draft = gmail_service.create_draft(payload)
        return {"status": "draft_created", "draft_id": draft.get("id")}
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error
    except Exception as error:
        raise HTTPException(502, "Gmail could not create the draft") from error


@app.post("/api/gmail/send")
def gmail_send(payload: EmailSendRequest) -> dict[str, Any]:
    if not payload.approved:
        raise HTTPException(400, "Explicit approval is required before sending email")
    try:
        sent = gmail_service.send(payload)
    except PermissionError as error:
        raise HTTPException(400, str(error)) from error
    except RuntimeError as error:
        raise HTTPException(503, str(error)) from error
    except Exception as error:
        raise HTTPException(502, "Gmail could not send the email") from error
    recipient = str(payload.to.email)
    write_audit("send_email", f"recipient={redacted_email(recipient)} approved=true result=sent")
    run = create_email_run("Send email", "completed", "Email sent")
    return {"status": "sent", "message_id": sent.get("id"), "run_id": run["id"]}


@app.get("/api/skills")
def list_skills() -> list[dict[str, Any]]:
    with db() as connection:
        return [skill_from_row(row) for row in connection.execute("SELECT * FROM skills ORDER BY created_at DESC")]


@app.post("/api/skills", status_code=201)
def create_skill(payload: SkillCreate) -> dict[str, Any]:
    skill_id = str(uuid.uuid4())
    created = now()
    with db() as connection:
        connection.execute(
            "INSERT INTO skills (id, name, description, steps, domains, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (skill_id, payload.name, payload.description, json.dumps([step.model_dump() for step in payload.steps]), json.dumps(payload.domains), created),
        )
        connection.execute("UPDATE skills SET tags = ?, capabilities = ? WHERE id = ?", (json.dumps(payload.tags), json.dumps(payload.capabilities), skill_id))
    write_audit("skill_created", payload.name)
    return {"id": skill_id, "name": payload.name, "description": payload.description, "steps": [step.model_dump() for step in payload.steps], "domains": payload.domains, "tags": payload.tags, "capabilities": payload.capabilities, "created_at": created, "last_run": None, "runs": 0, "usage_count": 0, "success_rate": 0}


@app.get("/api/skills/{skill_id}")
def get_skill(skill_id: str) -> dict[str, Any]:
    with db() as connection:
        row = connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Skill not found")
    return skill_from_row(row)


def _python_to_playwright_locator(target: dict[str, Any]) -> str | None:
    if not target:
        return None
    if target.get("test_id"):
        return "page.getByTestId(" + repr(target["test_id"]) + ")"
    if target.get("label"):
        return "page.getByLabel(" + repr(target["label"]) + ")"
    if target.get("placeholder"):
        return "page.getByPlaceholder(" + repr(target["placeholder"]) + ")"
    if target.get("css"):
        return "page.locator(" + repr(target["css"]) + ")"
    if target.get("xpath"):
        return "page.locator(" + repr("xpath=" + target["xpath"]) + ")"
    if target.get("role") and target.get("name"):
        return "page.getByRole(" + repr(target["role"]) + ", name=" + repr(target["name"]) + ")"
    if target.get("role") and target.get("text"):
        return "page.getByRole(" + repr(target["role"]) + ", { name: " + repr(target["text"][:60]) + " })"
    if target.get("text"):
        return "page.locator(" + repr("text=" + target["text"][:60]) + ")"
    if target.get("tag"):
        return "page.locator(" + repr(target["tag"]) + ")"
    return None


def _skill_to_playwright(skill: dict[str, Any]) -> str:
    name = skill.get("name", "skill")
    lines: list[str] = []
    lines.append("import { test, expect } from '@playwright/test';")
    lines.append("")
    lines.append("test(" + repr(name) + ", async ({ page }) => {")
    for step in skill.get("steps", []):
        stype = step.get("type")
        value = step.get("value")
        target = step.get("target") or {}
        if stype == "navigate":
            url = step.get("url") or value or "about:blank"
            lines.append("  await page.goto(" + repr(url) + ");")
            continue
        loc = _python_to_playwright_locator(target)
        if not loc and stype not in ("wait", "assert"):
            lines.append("  // skipped step with no target: " + str(stype))
            continue
        if stype == "wait":
            # value is the timeout in ms; if no target, it is a fixed sleep.
            try:
                timeout_ms = int(value or 500)
            except (TypeError, ValueError):
                timeout_ms = 500
            if target and loc:
                lines.append("  await " + loc + ".waitFor({ state: 'visible', timeout: " + str(timeout_ms) + " });")
            else:
                lines.append("  await page.waitForTimeout(" + str(timeout_ms) + ");")
            continue
        if stype == "assert":
            try:
                timeout_ms = int(value or 5000)
            except (TypeError, ValueError):
                timeout_ms = 5000
            if loc:
                lines.append("  await expect(" + loc + ").toBeVisible({ timeout: " + str(timeout_ms) + " });")
            else:
                lines.append("  // assert step has no target")
            continue
        if stype in ("click", "submit"):
            lines.append("  await " + loc + ".click();")
        elif stype == "type":
            lines.append("  await " + loc + ".fill(" + repr(value or "") + ");")
        elif stype == "press":
            lines.append("  await " + loc + ".press(" + repr(value or "Enter") + ");")
        elif stype == "select":
            lines.append("  await " + loc + ".selectOption(" + repr(value or "") + ");")
        elif stype == "check":
            lines.append("  await " + loc + ".check();")
        elif stype == "uncheck":
            lines.append("  await " + loc + ".uncheck();")
        elif stype == "scroll":
            lines.append("  await " + loc + ".scrollIntoViewIfNeeded();")
        else:
            lines.append("  // unsupported step type: " + str(stype))
    lines.append("});")
    lines.append("")
    return "\n".join(lines)


@app.get("/api/skills/{skill_id}/export/playwright")
def export_skill_playwright(skill_id: str) -> PlainTextResponse:
    skill = get_skill(skill_id)
    code = _skill_to_playwright(skill)
    safe = "".join(c if c.isalnum() or c in "-_" else "-" for c in skill["name"])[:60] or "skill"
    return PlainTextResponse(
        code,
        media_type="text/typescript",
        headers={"Content-Disposition": "attachment; filename=" + safe + ".spec.ts"},
    )


@app.put("/api/skills/{skill_id}")
def update_skill(skill_id: str, payload: SkillCreate) -> dict[str, Any]:
    with db() as connection:
        existing = connection.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
        if not existing:
            raise HTTPException(404, "Skill not found")
        connection.execute(
            "UPDATE skills SET name = ?, description = ?, steps = ?, domains = ? WHERE id = ?",
            (payload.name, payload.description, json.dumps([step.model_dump() for step in payload.steps]), json.dumps(payload.domains), skill_id),
        )
        connection.execute("UPDATE skills SET tags = ?, capabilities = ? WHERE id = ?", (json.dumps(payload.tags), json.dumps(payload.capabilities), skill_id))
    write_audit("skill_updated", payload.name)
    return get_skill(skill_id)


@app.delete("/api/skills/{skill_id}")
def delete_skill(skill_id: str) -> dict[str, bool]:
    with db() as connection:
        result = connection.execute("DELETE FROM skills WHERE id = ?", (skill_id,))
    if result.rowcount == 0:
        raise HTTPException(404, "Skill not found")
    write_audit("skill_deleted", skill_id)
    return {"deleted": True}


@app.get("/api/agent/tools")
def agent_tools() -> dict[str, Any]:
    return {"tools": agent_registry.descriptions()}


def current_agent_plan(request: str, variables: dict[str, str] | None = None) -> AgentPlan:
    with db() as connection:
        skills = [skill_from_row(row) for row in connection.execute("SELECT * FROM skills")]
    plan = calculate_risk(actionpilot_agent.plan(AgentRequest(request=request, variables=variables or {}), skills))
    write_audit("agent_planned", request)
    return plan


@app.post("/api/agent/plan")
def agent_plan(payload: AgentRequest) -> dict[str, Any]:
    return current_agent_plan(payload.request, payload.variables).model_dump()


def run_agent_request(payload: AgentRequest, plan: AgentPlan | None = None) -> dict[str, Any]:
    plan = plan or current_agent_plan(payload.request, payload.variables)
    if plan.intent == "run_skill" and plan.steps:
        step = plan.steps[0]
        run = create_run(RunCreate(skill_id=str(step.parameters["skill_id"]), task_name=task_title(plan.request), variables=plan.variables))
        return {"run_id": run["id"], "status": "running", "state": {"goal": plan.request, "plan": plan.model_dump(), "tool_history": [{"tool": "skill", "action": step.action}]}}
    run_id = create_pending_agent_run(plan)
    run_controls[run_id] = {"stop": threading.Event(), "pause": threading.Event()}
    threading.Thread(target=execute_agent_run, args=(run_id, plan.request, plan.variables), daemon=True).start()
    write_audit("agent_run_started", plan.request)
    return {"run_id": run_id, "status": "queued", "state": {"goal": plan.request, "plan": plan.model_dump(), "tool_history": []}}


@app.post("/api/agent/run")
def agent_run(payload: AgentRequest) -> dict[str, Any]:
    return run_agent_request(payload)


@app.get("/api/agent/runs/{run_id}")
def agent_run_detail(run_id: str) -> dict[str, Any]:
    return get_run_or_404(run_id)


@app.post("/api/agent/runs/{run_id}/pause")
def agent_pause(run_id: str) -> dict[str, Any]:
    return pause_run(run_id)


@app.post("/api/agent/runs/{run_id}/resume")
def agent_resume(run_id: str) -> dict[str, Any]:
    return resume_run(run_id)


@app.post("/api/agent/runs/{run_id}/stop")
def agent_stop(run_id: str) -> dict[str, Any]:
    return stop_run(run_id)


@app.get("/api/memory")
def memory_list() -> list[dict[str, Any]]:
    return memory_store.list()


@app.post("/api/memory", status_code=201)
def memory_create(payload: MemoryRequest) -> dict[str, Any]:
    item = memory_store.create(payload.type, payload.title, payload.value)
    write_audit("memory_created", f"{payload.type}: {payload.title}")
    return item


@app.put("/api/memory/{memory_id}")
def memory_update(memory_id: str, payload: MemoryRequest) -> dict[str, Any]:
    item = memory_store.update(memory_id, payload.title, payload.value, payload.type)
    if not item:
        raise HTTPException(404, "Memory not found")
    write_audit("memory_updated", payload.title)
    return item


@app.delete("/api/memory/{memory_id}")
def memory_delete(memory_id: str) -> dict[str, bool]:
    if not memory_store.delete(memory_id):
        raise HTTPException(404, "Memory not found")
    write_audit("memory_deleted", memory_id)
    return {"deleted": True}


@app.get("/api/routines")
def routine_list() -> list[dict[str, Any]]:
    return routine_store.list()


@app.post("/api/routines", status_code=201)
def routine_create(payload: RoutineRequest) -> dict[str, Any]:
    routine = routine_store.create(payload.name, payload.prompt, payload.schedule, payload.enabled)
    write_audit("routine_created", payload.name)
    return routine


@app.put("/api/routines/{routine_id}")
def routine_update(routine_id: str, payload: RoutineRequest) -> dict[str, Any]:
    item = routine_store.update(routine_id, payload.name, payload.prompt, payload.schedule, payload.enabled)
    if not item:
        raise HTTPException(404, "Routine not found")
    write_audit("routine_updated", payload.name)
    return item


@app.delete("/api/routines/{routine_id}")
def routine_delete(routine_id: str) -> dict[str, bool]:
    if not routine_store.delete(routine_id):
        raise HTTPException(404, "Routine not found")
    write_audit("routine_deleted", routine_id)
    return {"deleted": True}


@app.post("/api/routines/{routine_id}/run")
def routine_run(routine_id: str) -> dict[str, Any]:
    routine = next((item for item in routine_store.list() if item["id"] == routine_id), None)
    if not routine:
        raise HTTPException(404, "Routine not found")
    result = run_agent_request(AgentRequest(request=routine["prompt"]))
    routine_store.mark_run(routine_id)
    write_audit("routine_run", routine["name"])
    return result


@app.post("/api/routines/{routine_id}/pause")
def routine_pause(routine_id: str) -> dict[str, Any]:
    routine = next((item for item in routine_store.list() if item["id"] == routine_id), None)
    if not routine:
        raise HTTPException(404, "Routine not found")
    return routine_store.update(routine_id, routine["name"], routine["prompt"], routine["schedule"], False) or routine


@app.post("/api/routines/{routine_id}/resume")
def routine_resume(routine_id: str) -> dict[str, Any]:
    routine = next((item for item in routine_store.list() if item["id"] == routine_id), None)
    if not routine:
        raise HTTPException(404, "Routine not found")
    return routine_store.update(routine_id, routine["name"], routine["prompt"], routine["schedule"], True) or routine


@app.post("/api/agent/execute")
def agent_execute(payload: AgentExecuteRequest) -> dict[str, Any]:
    plan = calculate_risk(payload.plan)
    if plan.intent == "run_skill":
        if plan.requires_confirmation and not payload.approved:
            run = create_agent_run(plan, "waiting_confirmation", {})
            request_upfront_approval(run["id"], plan)
            return {"status": "waiting_confirmation", "requires_confirmation": True, "run_id": run["id"], "message": "Explicit approval is required before this action."}
        step = plan.steps[0]
        run = create_run(RunCreate(skill_id=str(step.parameters["skill_id"]), task_name=task_title(plan.request), variables=plan.variables))
        return {"status": "started", "run_id": run["id"], "tool": "skill"}
    if plan.intent == "local_account":
        # Deterministic local demo flow: run in the background and report live progress.
        return run_agent_request(payload, plan)
    if plan.intent in {"web_research", "research_and_email"}:
        tool = agent_registry.get("web_research")
        research_step = next((step for step in plan.steps if step.tool == "web_research"), None)
        if research_step is None:
            raise HTTPException(400, "Plan declares web research but contains no web_research step.")
        result = tool.execute(research_step, approved=payload.approved)
        if plan.intent == "research_and_email" and result.status == "completed" and gmail_service.status() == "connected":
            email_intent = parse_email_command(plan.request)
            if email_intent and email_intent.recipient_query:
                contacts = gmail_service.find_contacts(email_intent.recipient_query)
                if len(contacts) == 1:
                    source_text = "\n\n".join(f"{source.get('title', 'Source')}: {source.get('excerpt', '')[:500]}" for source in result.output.get("sources", []))
                    body = email_intent.body or "Here is the research summary."
                    if body.lower() in {"the summary", "summary"}:
                        body = source_text or body
                    else:
                        body = f"{body}\n\nResearch summary:\n{source_text}"
                    draft = gmail_service.create_draft(EmailDraft(to=contacts[0], subject="ActionPilot research summary", body=body))
                    result.output["draft_id"] = draft.get("id")
                    result.output["recipient"] = contacts[0].model_dump()
        run_status = "completed" if result.status == "completed" and not plan.requires_confirmation else "waiting_confirmation"
        run = create_agent_run(plan, run_status, result.output)
        if run_status == "waiting_confirmation":
            request_upfront_approval(run["id"], plan)
        return {"status": run_status, "run_id": run["id"], "output": result.output, "requires_confirmation": plan.requires_confirmation, "message": "Research complete. Email remains pending approval." if plan.intent == "research_and_email" else result.message}
    if plan.requires_confirmation and not payload.approved:
        run = create_agent_run(plan, "waiting_confirmation", {})
        request_upfront_approval(run["id"], plan)
        return {"status": "waiting_confirmation", "requires_confirmation": True, "run_id": run["id"], "message": "Explicit approval is required before this action."}
    return {"status": "clarify", "message": plan.message or "I could not determine how to execute this request."}


@app.post("/api/command")
def command(payload: CommandRequest) -> dict[str, Any]:
    agent_plan = current_agent_plan(payload.command)
    if agent_plan.intent in {"web_research", "research_and_email", "desktop", "local_account"}:
        result = agent_plan.model_dump()
        result["matched"] = True
        result["agent_plan"] = result.copy()
        return result
    email_intent = parse_email_command(payload.command)
    if email_intent:
        if email_intent.intent == "clarify":
            return email_intent.model_dump()
        if gmail_service.status() != "connected":
            email_intent.message = "Connect Gmail before preparing an email."
            return email_intent.model_dump()
        try:
            contacts = gmail_service.find_contacts(email_intent.recipient_query or "")
            email_intent.connected = True
            email_intent.candidates = contacts
            if len(contacts) != 1:
                email_intent.message = "Choose a recipient before preparing the email." if contacts else "No matching Gmail contact was found."
                return email_intent.model_dump()
            email_intent.recipient = contacts[0]
            if email_intent.intent == "reply_email":
                messages = gmail_service.recent_messages(f"from:({email_intent.recipient_query}) OR to:({email_intent.recipient_query})")
                if len(messages) != 1:
                    email_intent.message_candidates = messages
                    email_intent.message = "Choose the message to reply to." if messages else "No matching recent message was found."
                    return email_intent.model_dump()
                email_intent.message_id = messages[0].id
                email_intent.subject = f"Re: {messages[0].subject or ''}".strip()
            else:
                email_intent.subject = "ActionPilot message"
            draft = gmail_service.create_draft(EmailDraft(to=contacts[0], subject=email_intent.subject or "", body=email_intent.body or "", message_id=email_intent.message_id))
            result = email_intent.model_dump()
            result["draft_id"] = draft.get("id")
            return result
        except RuntimeError as error:
            email_intent.message = str(error)
            return email_intent.model_dump()
        except Exception:
            email_intent.message = "Gmail could not prepare the email."
            return email_intent.model_dump()
    with db() as connection:
        rows = connection.execute("SELECT * FROM skills").fetchall()
    result = match_command(payload.command, [skill_from_row(row) for row in rows])
    result["agent_plan"] = agent_plan.model_dump()
    write_audit("command_requested", payload.command)
    if result.get("matched") and payload.execute and not result["requires_confirmation"]:
        run = create_run(RunCreate(skill_id=result["skill_id"], task_name=result["skill"]["name"], variables=result["variables"]))
        result["run_id"] = run["id"]
    return result


@app.post("/api/runs")
def create_run(payload: RunCreate) -> dict[str, Any]:
    skill = get_skill(payload.skill_id)
    task_name = payload.task_name or skill["name"]
    run = {"id": str(uuid.uuid4()), "skill_id": payload.skill_id, "task_name": task_name, "status": "queued", "current_step": 0, "current_action": "Starting browser", "logs": ["Plan created. Starting browser."], "created_at": now(), "variables": payload.variables, "steps": []}
    with db() as connection:
        connection.execute("INSERT INTO runs (id, skill_id, task_name, status, current_step, logs, created_at, variables, plan) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (run["id"], payload.skill_id, task_name, run["status"], 0, json.dumps(run["logs"]), run["created_at"], json.dumps(payload.variables), json.dumps(skill["steps"])))
    run_controls[run["id"]] = {"stop": threading.Event(), "pause": threading.Event()}
    threading.Thread(target=execute_run, args=(run["id"], payload.skill_id, payload.variables), daemon=True).start()
    write_audit("run_created", task_name)
    return run


@app.get("/api/runs")
def list_runs() -> list[dict[str, Any]]:
    with db() as connection:
        rows = connection.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
    return [run_from_row(row) for row in rows]


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    return get_run_or_404(run_id)


@app.get("/api/runs/{run_id}/screenshot")
def get_run_screenshot(run_id: str) -> FileResponse:
    run = get_run_or_404(run_id)
    screenshot = contained_runtime_path(run.get("screenshot_path") or "")
    if not screenshot or not screenshot.is_file():
        raise HTTPException(404, "Screenshot not found")
    return FileResponse(screenshot, media_type="image/png", filename=screenshot.name)


@app.get("/api/runs/{run_id}/video")
def get_run_video(run_id: str):
    run = get_run_or_404(run_id)
    video_dir = contained_runtime_path(ROOT / "runtime" / "runs" / run["id"] / "video")
    if not video_dir or not video_dir.is_dir():
        raise HTTPException(404, "Video not found")
    files = sorted(video_dir.glob("*.webm"))
    if not files:
        raise HTTPException(404, "Video not found")
    # The recorder may still be writing (or have produced no bytes yet).
    # Starlette's FileResponse answers `Range: bytes=0-` on an empty file with
    # HTTP 416, which surfaces as a console error in the <video> element.
    # Serve an empty 200 body instead: no fabricated data, no 416, and the
    # player simply reports "no data". Non-empty files keep normal Range
    # behaviour (200/206) via FileResponse.
    if files[0].stat().st_size == 0:
        return Response(content=b"", media_type="video/webm", headers={"Content-Length": "0"})
    return FileResponse(files[0], media_type="video/webm", filename=files[0].name)


@app.get("/api/runs/{run_id}/step/{step_index}/screenshot")
def get_run_step_screenshot(run_id: str, step_index: int) -> FileResponse:
    get_run_or_404(run_id)
    with db() as connection:
        row = connection.execute("SELECT screenshot_path FROM run_steps WHERE run_id = ? AND step_index = ?", (run_id, step_index)).fetchone()
    if not row or not row[0]:
        raise HTTPException(404, "Step screenshot not found")
    path = contained_runtime_path(row[0])
    if not path or not path.is_file():
        raise HTTPException(404, "Step screenshot file missing")
    return FileResponse(path, media_type="image/png", filename=path.name)


run_controls: dict[str, dict[str, threading.Event]] = {}


def run_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["logs"] = json.loads(result.get("logs") or "[]")
    result["variables"] = json.loads(result.get("variables") or "{}")
    result["plan"] = json.loads(result.get("plan") or "[]")
    result["output"] = json.loads(result.get("output") or "{}")
    with db() as connection:
        result["steps"] = [dict(step) for step in connection.execute("SELECT * FROM run_steps WHERE run_id = ? ORDER BY step_index", (result["id"],))]
    return result


def get_run_or_404(run_id: str) -> dict[str, Any]:
    with db() as connection:
        row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Run not found")
    return run_from_row(row)


def set_run(run_id: str, status: str, **fields: Any) -> None:
    assignments = ["status = ?"]
    values: list[Any] = [status]
    for key, value in fields.items():
        assignments.append(f"{key} = ?")
        values.append(value)
    values.append(run_id)
    with db() as connection:
        row = connection.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            return
        validate_transition(row["status"], status)
        connection.execute(f"UPDATE runs SET {', '.join(assignments)} WHERE id = ?", values)


def safe_set_run(run_id: str, status: str, **fields: Any) -> None:
    """Best-effort status write for background threads: skips races with terminal states."""
    try:
        set_run(run_id, status, **fields)
    except InvalidTransition:
        pass


def reconcile_interrupted_runs() -> int:
    """Startup reconciliation: fail runs left non-terminal by a process restart.

    Selects only current non-terminal statuses, so terminal runs are never
    touched and rerunning this is a no-op (no duplicate audit events).
    """
    non_terminal = tuple(status for status in RUN_STATUSES if status not in TERMINAL_RUN_STATUSES)
    with db() as connection:
        rows = connection.execute(
            f"SELECT id, task_name FROM runs WHERE status IN ({', '.join('?' for _ in non_terminal)})",
            non_terminal,
        ).fetchall()
    for row in rows:
        # Every non-terminal status already allows -> failed in the transition
        # table, so reconciliation validates like any other run transition.
        set_run(row["id"], "failed", error="Interrupted by backend restart")
        write_audit("run_interrupted", row["task_name"] or row["id"])
    return len(rows)


def execution_progress(run_id: str, event: str, step_index: int, data: dict[str, Any]) -> None:
    timestamp = now()
    if event == "step_started":
        step = data["step"]
        with db() as connection:
            connection.execute("INSERT INTO run_steps (id, run_id, step_index, label, action_type, status, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (str(uuid.uuid4()), run_id, step_index, step.get("label"), step.get("type"), "running", timestamp))
        safe_set_run(run_id, "running", current_step=step_index, current_action=step.get("label", step.get("type", "Browser action")), error=None)
    elif event == "step_screenshot":
        with db() as connection:
            connection.execute("UPDATE run_steps SET screenshot_path = ? WHERE run_id = ? AND step_index = ?", (data.get("screenshot_path"), run_id, step_index))
    elif event == "step_completed":
        with db() as connection:
            connection.execute("UPDATE run_steps SET status = ?, completed_at = ?, url = ?, title = ?, verification = ? WHERE run_id = ? AND step_index = ?", ("completed", timestamp, data.get("url"), data.get("title"), json.dumps(data.get("verification")), run_id, step_index))
    elif event == "step_failed":
        with db() as connection:
            connection.execute("UPDATE run_steps SET status = ?, completed_at = ?, error = ?, screenshot_path = ?, url = ?, title = ? WHERE run_id = ? AND step_index = ?", ("failed", timestamp, data.get("error"), data.get("screenshot_path"), data.get("url"), data.get("title"), run_id, step_index))
        safe_set_run(run_id, "failed", error=data.get("error"), screenshot_path=data.get("screenshot_path"))
    elif event == "waiting_confirmation":
        safe_set_run(run_id, "waiting_confirmation", current_step=step_index, current_action="Confirmation required", error=data.get("message"))


def execute_run(run_id: str, skill_id: str, variables: dict[str, str]) -> None:
    controls = run_controls.get(run_id, {"stop": threading.Event(), "pause": threading.Event()})
    try:
        skill = get_skill(skill_id)
        _headless = os.getenv("ACTIONPILOT_HEADLESS", "1") == "1"
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            asyncio.set_event_loop(asyncio.new_event_loop())
        executor = BrowserExecutor(ROOT / "runtime" / "runs" / run_id, lambda event, index, data: execution_progress(run_id, event, index, data), headless=_headless)
        outcomes = executor.execute(skill["steps"], variables, controls["stop"], controls["pause"], gate=approval_gate(run_id, controls))
        if controls["stop"].is_set():
            safe_set_run(run_id, "stopped", current_action="Stopped by user")
        elif outcomes:
            safe_set_run(run_id, "completed", current_step=len(outcomes), current_action="Complete")
            with db() as connection:
                connection.execute("UPDATE skills SET runs = runs + 1, usage_count = usage_count + 1, last_run = ?, success_rate = CASE WHEN runs = 0 THEN 100 ELSE ((success_rate * runs) + 100) / (runs + 1) END WHERE id = ?", (now(), skill_id))
        else:
            safe_set_run(run_id, "completed", current_action="Complete")
    except ConfirmationRequired as error:
        safe_set_run(run_id, "waiting_confirmation", error=str(error), current_action="Confirmation required")
    except ExecutionStopped as error:
        safe_set_run(run_id, "stopped", current_action=str(error) or "Stopped by user")
    except Exception as error:
        if not controls["stop"].is_set():
            safe_set_run(run_id, "failed", error=describe_error(error), current_action="Failed")
    finally:
        run_controls.pop(run_id, None)


@app.post("/api/teach/start")
def start_teaching(payload: TeachStart) -> dict[str, Any]:
    session_id = str(uuid.uuid4())
    teach_sessions[session_id] = {"name": payload.name, "description": payload.description, "steps": []}
    write_audit("teaching_started", payload.name)
    return {"session_id": session_id, "name": payload.name, "status": "recording"}


@app.post("/api/teach/{session_id}/action")
def record_teaching_action(session_id: str, payload: TeachEvent) -> dict[str, Any]:
    session = teach_sessions.get(session_id)
    if not session:
        raise HTTPException(404, "Teaching session not found")
    if is_sensitive_event(payload):
        return {"recorded": False, "reason": "Sensitive fields are never recorded."}
    step = payload.model_dump(exclude_none=True)
    step.pop("input_type", None)
    session["steps"].append(step)
    return {"recorded": True, "step_number": len(session["steps"]), "step": step}


def _collapse_type_steps(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    collapsed: list[dict[str, Any]] = []
    for step in steps:
        if (collapsed and step.get("type") == "type" and collapsed[-1].get("type") == "type"
                and step.get("target") == collapsed[-1].get("target")):
            collapsed[-1] = step
            continue
        collapsed.append(step)
    return collapsed


@app.post("/api/teach/{session_id}/finish")
def finish_teaching(session_id: str) -> dict[str, Any]:
    session = teach_sessions.pop(session_id, None)
    if not session:
        raise HTTPException(404, "Teaching session not found")
    steps = _collapse_type_steps(session["steps"])
    domains = sorted({parsed.netloc for parsed in (urlparse(step.get("url", "")) for step in steps) if parsed.netloc})
    return create_skill(SkillCreate(name=session["name"], description=session["description"], domains=domains, steps=[Step(**step) for step in steps]))


@app.post("/api/runs/{run_id}/pause")
def pause_run(run_id: str) -> dict[str, Any]:
    run = get_run_or_404(run_id)
    if run["status"] in TERMINAL_RUN_STATUSES or run["status"] == "paused":
        return run
    controls = run_controls.get(run_id)
    if controls:
        controls["pause"].set()
    try:
        set_run(run_id, "paused", current_action="Paused by user")
    except InvalidTransition as error:
        raise HTTPException(409, str(error)) from error
    write_audit("run_paused", run["task_name"])
    return get_run_or_404(run_id)


@app.post("/api/runs/{run_id}/resume")
def resume_run(run_id: str) -> dict[str, Any]:
    run = get_run_or_404(run_id)
    if run["status"] in TERMINAL_RUN_STATUSES or run["status"] == "running":
        return run
    controls = run_controls.get(run_id)
    if controls:
        controls["pause"].clear()
    try:
        set_run(run_id, "running", current_action="Resuming")
    except InvalidTransition as error:
        raise HTTPException(409, str(error)) from error
    write_audit("run_resumed", run["task_name"])
    return get_run_or_404(run_id)


@app.post("/api/runs/{run_id}/stop")
def stop_run(run_id: str) -> dict[str, Any]:
    run = get_run_or_404(run_id)
    if run["status"] in TERMINAL_RUN_STATUSES:
        return run
    controls = run_controls.get(run_id)
    if controls:
        controls["stop"].set()
    try:
        set_run(run_id, "stopped", current_action="Stopped by user")
    except InvalidTransition as error:
        raise HTTPException(409, str(error)) from error
    write_audit("run_stopped", run["task_name"])
    return get_run_or_404(run_id)


def approval_from_row(row: sqlite3.Row) -> dict[str, Any]:
    approval = dict(row)
    approval["detail"] = json.loads(approval.get("detail") or "{}")
    return approval


def sanitize_approval_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """Strip typed text from stored approval evidence.

    The executor holds the real step in memory and nothing reads the stored
    detail back to perform the action, so typed values never need to persist
    here. Everything else (action, target, risk, session ids) stays intact.
    """
    cleaned: dict[str, Any] = {}
    for key, value in detail.items():
        if key == "value" and isinstance(value, str) and value:
            cleaned[key] = "[redacted]"
        elif key == "parameters" and isinstance(value, dict):
            cleaned[key] = {
                name: ("[redacted]" if name == "value" and isinstance(entry, str) and entry else entry)
                for name, entry in value.items()
            }
        else:
            cleaned[key] = value
    return cleaned


def create_approval(run_id: str, step_index: int, summary: str, detail: dict[str, Any], kind: str = "step") -> str:
    approval_id = str(uuid.uuid4())
    with db() as connection:
        connection.execute(
            "INSERT INTO approvals (id, run_id, step_index, kind, summary, detail, status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (approval_id, run_id, step_index, kind, summary, json.dumps(sanitize_approval_detail(detail)), "pending", now()),
        )
    return approval_id


def request_upfront_approval(run_id: str, plan: AgentPlan) -> None:
    """Attach the single approval row for an upfront-gated waiting run."""
    index = first_high_risk_index(plan)
    step = plan.steps[index] if plan.steps else None
    summary = step.action if step else task_title(plan.request)
    detail = step.model_dump() if step else {"action": task_title(plan.request), "risk": "high"}
    create_approval(run_id, index, summary, detail, kind="upfront")
    write_audit("approval_requested", f"step {index + 1}: {summary}")


def approval_status(approval_id: str) -> str | None:
    with db() as connection:
        row = connection.execute("SELECT status FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    return str(row["status"]) if row else None


def approved_approval_exists(run_id: str, step_index: int) -> bool:
    with db() as connection:
        row = connection.execute(
            "SELECT 1 FROM approvals WHERE run_id = ? AND step_index = ? AND status = 'approved' LIMIT 1",
            (run_id, step_index),
        ).fetchone()
    return row is not None


def approval_gate(run_id: str, controls: dict[str, threading.Event]):
    """Blocks a high-risk step until its approval row is resolved or the run stops."""

    def gate(index: int, step: dict[str, Any]) -> str | None:
        # An upfront approval already covers this step: proceed without asking again.
        if approved_approval_exists(run_id, index):
            return None
        summary = str(step.get("label") or step.get("action") or "High-risk action")
        approval_id = create_approval(run_id, index, summary, step)
        safe_set_run(run_id, "waiting_confirmation", current_step=index, current_action="Waiting for approval", error=None)
        write_audit("approval_requested", f"step {index + 1}: {summary}")
        while True:
            if controls["stop"].is_set():
                return "Run stopped by user"
            status = approval_status(approval_id)
            if status == "approved":
                return None
            if status == "rejected":
                return "Approval rejected"
            time.sleep(0.1)

    return gate


@app.get("/api/activity")
def activity(limit: int = 100) -> list[dict[str, Any]]:
    bounded = max(1, min(limit, 500))
    with db() as connection:
        rows = connection.execute("SELECT * FROM audit_logs ORDER BY created_at DESC, rowid DESC LIMIT ?", (bounded,)).fetchall()
    return [dict(row) for row in rows]


@app.get("/api/approvals")
def list_approvals(status: str | None = None, run_id: str | None = None) -> list[dict[str, Any]]:
    if status is not None and status not in {"pending", "approved", "rejected"}:
        raise HTTPException(400, "status must be pending, approved, or rejected")
    query = "SELECT * FROM approvals"
    clauses: list[str] = []
    values: list[Any] = []
    if status:
        clauses.append("status = ?")
        values.append(status)
    if run_id:
        clauses.append("run_id = ?")
        values.append(run_id)
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY created_at DESC, rowid DESC"
    with db() as connection:
        rows = connection.execute(query, values).fetchall()
    return [approval_from_row(row) for row in rows]


def _resolve_approval(approval_id: str, decision: str) -> dict[str, Any]:
    with db() as connection:
        row = connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Approval not found")
        updated = connection.execute(
            "UPDATE approvals SET status = ?, resolved_at = ? WHERE id = ? AND status = 'pending'",
            (decision, now(), approval_id),
        )
        if updated.rowcount == 0:
            raise HTTPException(409, "Approval has already been resolved")
        approval = approval_from_row(connection.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone())
        run_row = connection.execute("SELECT status FROM runs WHERE id = ?", (approval["run_id"],)).fetchone()
    if run_row and run_row["status"] == "waiting_confirmation":
        if decision == "approved":
            safe_set_run(approval["run_id"], "running", current_action="Approved - resuming")
        else:
            safe_set_run(approval["run_id"], "stopped", current_action="Approval rejected")
    return approval


def resume_upfront_run(run_id: str) -> None:
    """Continue an upfront-gated run now that its plan-level approval is granted."""
    with db() as connection:
        row = connection.execute("SELECT status, plan, variables, task_name FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row or row["status"] != "running":
        return
    plan_data = json.loads(row["plan"] or "{}")
    variables = json.loads(row["variables"] or "{}")
    if plan_data.get("intent") == "run_skill":
        steps = plan_data.get("steps") or [{}]
        parameters = steps[0].get("parameters") or {}
        skill_id = str(parameters.get("skill_id") or "")
        if not skill_id:
            return
        target, args = execute_run, (run_id, skill_id, variables)
    else:
        request = str(plan_data.get("request") or row["task_name"])
        target, args = execute_agent_run, (run_id, request, variables)
    run_controls[run_id] = {"stop": threading.Event(), "pause": threading.Event()}
    threading.Thread(target=target, args=args, daemon=True).start()


@app.post("/api/approvals/{approval_id}/approve")
def approve_approval(approval_id: str) -> dict[str, Any]:
    approval = _resolve_approval(approval_id, "approved")
    write_audit("approval_approved", f"step {approval['step_index'] + 1}: {approval['summary']}")
    if approval.get("kind") == "upfront":
        resume_upfront_run(approval["run_id"])
    return approval


@app.post("/api/approvals/{approval_id}/reject")
def reject_approval(approval_id: str) -> dict[str, Any]:
    approval = _resolve_approval(approval_id, "rejected")
    write_audit("approval_rejected", f"step {approval['step_index'] + 1}: {approval['summary']}")
    return approval


def create_pending_agent_run(plan: AgentPlan) -> str:
    run_id = str(uuid.uuid4())
    created = now()
    with db() as connection:
        connection.execute(
            "INSERT INTO runs (id, skill_id, task_name, status, current_step, logs, created_at, variables, current_action, tool, plan, output, requires_confirmation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, None, task_title(plan.request), "queued", 0, json.dumps([step.action for step in plan.steps]), created, json.dumps(plan.variables), "Planning", plan.steps[0].tool if plan.steps else None, plan.model_dump_json(), json.dumps({}), int(plan.requires_confirmation)),
        )
        for index, step in enumerate(plan.steps):
            connection.execute(
                "INSERT INTO run_steps (id, run_id, step_index, label, action_type, status, started_at) VALUES (?, ?, ?, ?, ?, ?, NULL)",
                (str(uuid.uuid4()), run_id, index, step.action, step.tool, "pending"),
            )
    return run_id


def agent_progress(run_id: str, event: str, step_index: int, data: dict[str, Any]) -> None:
    timestamp = now()
    step = data.get("step") or {}
    label = step.get("label") or step.get("action") or "Agent action"
    action_type = step.get("type") or step.get("tool") or "agent"
    if event == "step_started":
        with db() as connection:
            updated = connection.execute(
                "UPDATE run_steps SET label = ?, action_type = ?, status = ?, started_at = ? WHERE run_id = ? AND step_index = ?",
                (label, action_type, "running", timestamp, run_id, step_index),
            )
            if updated.rowcount == 0:
                connection.execute(
                    "INSERT INTO run_steps (id, run_id, step_index, label, action_type, status, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (str(uuid.uuid4()), run_id, step_index, label, action_type, "running", timestamp),
                )
        safe_set_run(run_id, "running", current_step=step_index, current_action=label, error=None)
        write_audit("agent_step_started", label)
    elif event == "step_completed":
        output = data.get("output") or {}
        verification = output.get("verification")
        with db() as connection:
            connection.execute(
                "UPDATE run_steps SET status = ?, completed_at = ?, url = COALESCE(?, url), title = COALESCE(?, title), screenshot_path = COALESCE(?, screenshot_path), verification = COALESCE(?, verification) WHERE run_id = ? AND step_index = ?",
                ("completed", timestamp, output.get("url"), output.get("title"), output.get("screenshot_path"), json.dumps(verification) if verification is not None else None, run_id, step_index),
            )
        write_audit("agent_step_completed", label)
    elif event == "step_failed":
        output = data.get("output") or {}
        verification = output.get("verification")
        with db() as connection:
            connection.execute(
                "UPDATE run_steps SET status = ?, completed_at = ?, error = ?, url = COALESCE(?, url), title = COALESCE(?, title), screenshot_path = COALESCE(?, screenshot_path), verification = COALESCE(?, verification) WHERE run_id = ? AND step_index = ?",
                ("failed", timestamp, data.get("error"), output.get("url"), output.get("title"), output.get("screenshot_path"), json.dumps(verification) if verification is not None else None, run_id, step_index),
            )
        safe_set_run(run_id, "failed", error=data.get("error"), current_action="Failed")
        write_audit("agent_step_failed", label)
    elif event == "waiting_approval":
        with db() as connection:
            connection.execute("UPDATE run_steps SET status = ? WHERE run_id = ? AND step_index = ?", ("waiting_confirmation", run_id, step_index))
        safe_set_run(run_id, "waiting_confirmation", current_step=step_index, current_action="Waiting for approval", error=None)
    elif event == "observe":
        write_audit("observe", f"step {step_index + 1}: {data.get('summary', '')}")
    elif event == "decide":
        write_audit("decide", f"step {step_index + 1}: {data.get('kind', 'execute')} — {data.get('reason', '')}")
    elif event == "verify":
        write_audit("verify", f"step {step_index + 1}: {'passed' if data.get('passed') else 'failed'} — {data.get('summary', '')}")
    elif event == "recover":
        write_audit("recover", f"step {step_index + 1}: {data.get('kind', 'stop')} — {data.get('reason', '')}")


def execute_agent_run(run_id: str, request: str, variables: dict[str, str]) -> None:
    controls = run_controls.get(run_id) or {"stop": threading.Event(), "pause": threading.Event()}
    try:
        state = agent_loop.run(
            request,
            [],
            variables,
            stop_event=controls["stop"],
            pause_event=controls["pause"],
            gate=approval_gate(run_id, controls),
            progress=lambda event, index, data: agent_progress(run_id, event, index, data),
        )
        preferences = memory_store.relevant(request)
        if preferences:
            state.result = {**(state.result or {}), "memory_preferences": preferences}
        with db() as connection:
            connection.execute("UPDATE runs SET output = ? WHERE id = ?", (json.dumps(state.model_dump()), run_id))
        final_action = {
            "completed": "Complete",
            "failed": "Failed",
            "stopped": state.error or "Stopped by user",
            "waiting_confirmation": "Waiting for approval",
        }.get(state.status, state.status)
        safe_set_run(run_id, state.status, current_step=state.current_step, current_action=final_action, error=state.error)
        write_audit("agent_run_finished", f"{state.status}: {request[:120]}")
    except Exception as error:
        if not controls["stop"].is_set():
            safe_set_run(run_id, "failed", error=describe_error(error), current_action="Failed")
        write_audit("agent_run_finished", f"failed: {request[:120]}")
    finally:
        try:
            agent_registry.get("browser").close_sessions(threading.get_ident())
        except Exception:
            pass
        run_controls.pop(run_id, None)
