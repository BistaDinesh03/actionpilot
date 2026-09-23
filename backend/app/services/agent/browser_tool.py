from __future__ import annotations

import re
import tempfile
import threading
import uuid
from pathlib import Path
from threading import Event
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

from .models import AgentRequest, PlanStep, ToolResult
from .observer import observe_page
from ..computer.observation import from_browser
from ..execution.browser import BrowserSession
from ..execution.executor import BrowserExecutor
from ..execution.models import ExecutionContext

# The account flow only ever runs against the local demo site.
DEFAULT_DEMO_URL = "http://127.0.0.1:4173/account.html"
LOCAL_HOSTS = {"127.0.0.1", "localhost"}


class BrowserTool:
    name = "browser"
    description = "Safely browse pages, run the local account demo end to end, and return bounded visible observations."
    capabilities = ["open URL", "search", "click", "type", "press", "scroll", "read page", "open links", "screenshot", "fill local demo form", "verify page result"]
    risk_level = "low"

    def __init__(self, runtime_dir: Path | str | None = None) -> None:
        # Sessions and screenshots live under runtime_dir (per-session subdirectory).
        self.runtime_root = Path(runtime_dir) if runtime_dir else Path(tempfile.gettempdir()) / "actionpilot-agent"
        self._executor = BrowserExecutor(self.runtime_root, headless=True)
        self._sessions: dict[str, BrowserSession] = {}
        self._session_threads: dict[str, int] = {}

    def can_handle(self, request: AgentRequest) -> bool:
        return True

    def plan(self, request: AgentRequest) -> list[PlanStep]:
        return [PlanStep(tool=self.name, action="open and observe public page", risk="low", parameters={"request": request.request, "url": request.variables.get("url")})]

    # --- local account demo: plan ------------------------------------------

    def plan_account(self, request: AgentRequest) -> list[PlanStep]:
        base = self._account_parameters(request)
        phases = [
            ("open", "Open the local account demo page"),
            ("fill", f"Fill the account form for {base['name']}"),
            ("submit", "Submit the account form"),
            ("verify", "Verify the account was created"),
        ]
        return [PlanStep(tool=self.name, action=action, risk="low", parameters={**base, "phase": phase}) for phase, action in phases]

    @staticmethod
    def _derive_email(name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", ".", name.lower()).strip(".")
        return f"{slug or 'demo.user'}@example.com"

    def _account_parameters(self, request: AgentRequest) -> dict[str, str]:
        variables = request.variables
        parsed = re.search(r"\bfor\s+([^.!?\n]+)", request.request)
        name = (variables.get("name") or (parsed.group(1).strip() if parsed else "") or "Demo User").strip()[:80]
        return {
            "session_id": uuid.uuid4().hex,
            "url": variables.get("url") or DEFAULT_DEMO_URL,
            "name": name,
            "email": variables.get("email") or self._derive_email(name),
            "account_type": variables.get("account_type") or "personal",
            "country": variables.get("country") or "us",
        }

    # --- local account demo: execution -------------------------------------

    @staticmethod
    def _local_url_error(url: str) -> str | None:
        parsed = urlparse(str(url))
        if parsed.scheme not in {"http", "https"} or (parsed.hostname or "") not in LOCAL_HOSTS:
            return f"Refusing to run: the account demo only runs on the local demo site (got {url})."
        return None

    def _start_session(self, parameters: dict[str, Any]) -> tuple[BrowserSession, Any]:
        session_id = str(parameters["session_id"])
        session = self._sessions.get(session_id)
        page = session.page if session else None
        if session is None or page is None:
            session = BrowserSession(self.runtime_root / session_id, headless=True)
            page = session.start()
            self._sessions[session_id] = session
            self._session_threads[session_id] = threading.get_ident()
        # Always (re)navigate so a retried open phase recovers a broken page.
        context = ExecutionContext(Event(), Event())
        self._executor.execute_step(page, {"type": "navigate", "label": "Open the local account demo", "url": parameters["url"]}, context)
        return session, page

    def _page(self, parameters: dict[str, Any]) -> Any:
        session = self._sessions.get(str(parameters["session_id"]))
        if session is None or session.page is None:
            raise RuntimeError("browser session is not open")
        return session.page

    @staticmethod
    def _context() -> ExecutionContext:
        return ExecutionContext(Event(), Event())

    def _phase_open(self, parameters: dict[str, Any]) -> ToolResult:
        url = str(parameters["url"])
        if error := self._local_url_error(url):
            return ToolResult(status="failed", message=error, output={"phase": "open"})
        session, page = self._start_session(parameters)
        observation = observe_page(page)
        return ToolResult(status="completed", output={"phase": "open", "url": page.url, "title": page.title(), "screenshot_path": session.screenshot("open.png"), "observation": observation.model_dump()})

    def _phase_fill(self, parameters: dict[str, Any]) -> ToolResult:
        page = self._page(parameters)
        context = self._context()
        account_type = str(parameters["account_type"])
        sub_steps = [
            {"type": "type", "label": "Type full name", "target": {"css": "#fullName"}, "value": parameters["name"]},
            {"type": "type", "label": "Type email address", "target": {"css": "#email"}, "value": parameters["email"]},
            {"type": "check", "label": "Select account type", "target": {"css": f'input[name="accountType"][value="{account_type}"]'}},
            {"type": "check", "label": "Accept the terms", "target": {"css": "#terms"}},
            {"type": "select", "label": "Select country", "target": {"css": "#country"}, "value": parameters["country"]},
        ]
        for sub_step in sub_steps:
            self._executor.execute_step(page, sub_step, context)
        session = self._sessions[str(parameters["session_id"])]
        return ToolResult(status="completed", output={
            "phase": "fill",
            "url": page.url,
            "title": page.title(),
            "screenshot_path": session.screenshot("fill.png"),
            "filled": {"name": parameters["name"], "email": parameters["email"], "account_type": account_type, "country": parameters["country"]},
        })

    def _phase_submit(self, parameters: dict[str, Any]) -> ToolResult:
        page = self._page(parameters)
        self._executor.execute_step(page, {"type": "click", "label": "Submit the account form", "target": {"css": "#submitBtn"}}, self._context())
        session = self._sessions[str(parameters["session_id"])]
        return ToolResult(status="completed", output={"phase": "submit", "submitted": True, "url": page.url, "title": page.title(), "screenshot_path": session.screenshot("submit.png")})

    def _phase_verify(self, parameters: dict[str, Any]) -> ToolResult:
        session = self._sessions.get(str(parameters["session_id"]))
        if session is None or session.page is None:
            # Self-heal after a crashed session: reopen the page before judging.
            url_error = self._local_url_error(str(parameters["url"]))
            if url_error:
                return ToolResult(status="failed", message=url_error, output={"phase": "verify"})
            session, _page = self._start_session(parameters)
        page = session.page
        visible = True
        try:
            page.wait_for_selector("#result.show", timeout=2_500)
        except Exception:
            visible = False
        observation = observe_page(page)
        screenshot = session.screenshot("verify.png")
        common = {"phase": "verify", "url": page.url, "title": page.title(), "screenshot_path": screenshot}
        if not visible:
            visible_errors = page.locator(".err.show").all_text_contents()
            message = "Account creation could not be verified: success panel not visible"
            if visible_errors:
                message += f" — page errors: {'; '.join(text.strip() for text in visible_errors)}"
            return ToolResult(status="failed", message=message, output={**common, "verification": {"passed": False, "checks": {"result_visible": False}, "visible_errors": visible_errors}})
        observed = {
            "name": page.locator("#sumName").inner_text(),
            "email": page.locator("#sumEmail").inner_text(),
            "account_type": page.locator("#sumType").inner_text(),
            "country": page.locator("#sumCountry").inner_text(),
        }
        expected = {
            "name": str(parameters["name"]),
            "email": str(parameters["email"]),
            "account_type": "Business" if parameters["account_type"] == "business" else "Personal",
            "country": (page.locator(f'#country option[value="{parameters["country"]}"]').text_content() or str(parameters["country"])).strip(),
        }
        checks = {
            "success_message": "Account created successfully" in str(observation.data.get("visible_text", "")),
            "result_visible": True,
            "name": observed["name"] == expected["name"],
            "email": observed["email"] == expected["email"],
            "account_type": observed["account_type"] == expected["account_type"],
            "country": observed["country"] == expected["country"],
        }
        verification = {"passed": all(checks.values()), "checks": checks, "observed": observed, "expected": expected}
        if verification["passed"]:
            verification["summary"] = f"Account created for {expected['name']} ({expected['account_type']}, {expected['country']}) on the local demo."
            return ToolResult(status="completed", output={**common, "verification": verification})
        failed = [key for key, ok in checks.items() if not ok]
        verification["summary"] = f"Not verified: mismatch on {', '.join(failed)}."
        return ToolResult(status="failed", message=f"Account creation could not be verified: mismatch on {', '.join(failed)}.", output={**common, "verification": verification})

    def execute(self, plan: PlanStep, approved: bool = False) -> ToolResult:
        phase = plan.parameters.get("phase")
        if phase:
            try:
                handlers = {"open": self._phase_open, "fill": self._phase_fill, "submit": self._phase_submit, "verify": self._phase_verify}
                handler = handlers.get(str(phase))
                if handler is None:
                    return ToolResult(status="failed", message=f"Unknown account task phase: {phase}", output={"phase": str(phase)})
                return handler(plan.parameters)
            except Exception as error:
                return ToolResult(status="failed", message=f"{phase} phase failed: {error}", output={"phase": str(phase)})
        url = plan.parameters.get("url")
        if not url:
            return ToolResult(status="completed", output={"message": "No URL was supplied for browser observation."})
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(str(url), wait_until="domcontentloaded", timeout=20_000)
                observation = observe_page(page)
                browser.close()
            raw = observation.model_dump()
            return ToolResult(status="completed", output={**raw, "observation": from_browser(raw).model_dump()})
        except Exception:
            return ToolResult(status="failed", message="Browser observation failed safely.")

    def close_sessions(self, thread_id: int | None = None) -> None:
        """Close sessions created by the given thread (or all sessions)."""
        owned = [sid for sid, owner in self._session_threads.items() if thread_id is None or owner == thread_id]
        for session_id in owned:
            session = self._sessions.pop(session_id, None)
            self._session_threads.pop(session_id, None)
            if session is not None:
                session.close()
