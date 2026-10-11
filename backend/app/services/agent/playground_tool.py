"""Local-only deterministic driver for the ActionPilot Playground.

The playground is a small static site of synthetic UI scenarios
(``playground-site/``) used to prove the adaptive execution seams
(observe -> decide -> runtime risk -> act -> verify -> recover -> approve)
without AI, cloud services, external sites, or real accounts.

This module is intentionally small and easy to delete. It is NOT
registered in the production tool registry and is only used directly by
the playground tests and the documented manual flow.

All waits are hard-bounded; nothing here polls or loops freely.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Page

from ..computer.observation import from_browser
from ..execution.browser import BrowserSession
from .browser_tool import LOCAL_HOSTS, SESSION_ID_PATTERN, BrowserTool
from .models import AgentRequest, Decision, MAX_RETARGETS, PlanStep, ToolResult, VerificationResult
from .observer import observe_page
from .state import Observation

# Hard bounds for the playground driver (nothing here may poll or loop freely).
DEFAULT_WAIT_TIMEOUT_MS = 2000
MAX_WAIT_TIMEOUT_MS = 5000
ACTION_TIMEOUT_MS = 2000
GOTO_TIMEOUT_MS = 5000
MAX_FIELDS = 8


class PlaygroundTool:
    """Drives the deterministic local playground scenarios."""

    name = "playground"
    description = "Drive the local ActionPilot playground (deterministic, local-only scenarios)."
    capabilities = ["observe playground", "fill playground form", "click playground controls", "verify playground state"]
    risk_level = "low"

    def __init__(self, runtime_dir: Any = None) -> None:
        self.runtime_root = Path(runtime_dir) if runtime_dir else Path(tempfile.mkdtemp(prefix="actionpilot-playground-"))
        # One shared Playwright session (the sync API may only run once per
        # process); each playground session_id maps to its own page/tab.
        self._session: BrowserSession | None = None
        self._pages: dict[str, Page] = {}
        self.execute_calls = 0  # deterministic bounds instrumentation for tests

    # ------------------------------------------------------------------
    # registry protocol (the playground is driven directly, never routed)
    def can_handle(self, request: AgentRequest) -> bool:
        return True

    def plan(self, request: AgentRequest) -> list[PlanStep]:
        return []

    # ------------------------------------------------------------------
    # session helpers
    def _start_session(self, session_id: str) -> tuple[BrowserSession, Page]:
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            raise RuntimeError(f"Refusing to run: invalid playground session id {session_id!r}.")
        if self._session is None:
            self._session = BrowserSession(self.runtime_root, headless=True)
            self._session.start()
        context = self._session.context
        if context is None:
            raise RuntimeError("Playground browser context is not available.")
        page = context.new_page()
        page.set_default_timeout(ACTION_TIMEOUT_MS)
        self._pages[session_id] = page
        return self._session, page

    def _page(self, plan: PlanStep) -> Page:
        session_id = str(plan.parameters.get("session_id") or "")
        page = self._pages.get(session_id)
        if page is None:
            raise RuntimeError("No playground session is open for this step; open the scenario first.")
        return page

    def page_for(self, session_id: str) -> Page | None:
        """Public inspection hook: lets tests read the scenario state directly."""
        return self._pages.get(str(session_id))

    def _screenshot(self, session_id: str, name: str) -> str | None:
        page = self._pages.get(session_id)
        if page is None:
            return None
        target = self.runtime_root / session_id / name
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            page.screenshot(path=str(target))
        except Exception:
            return None
        return str(target)

    def close_sessions(self) -> None:
        for page in list(self._pages.values()):
            try:
                page.close()
            except Exception:
                pass
        self._pages.clear()
        if self._session is not None:
            self._session.close()
            self._session = None

    # ------------------------------------------------------------------
    # deterministic state read (read-only; returns None when unavailable)
    @staticmethod
    def _state(page: Page) -> dict[str, Any] | None:
        try:
            value = page.evaluate("() => (window.__playground ? window.__playground.state : null)")
        except Exception:
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _resolve(page: Page, target: dict[str, Any]) -> Any:
        if target.get("css"):
            return page.locator(str(target["css"]))
        if target.get("id"):
            return page.locator(f"#{target['id']}")
        if target.get("name"):
            return page.get_by_role("button", name=str(target["name"]), exact=True)
        raise ValueError("Playground target requires css, id, or semantic name.")

    # ------------------------------------------------------------------
    # observation seam (bounded, read-only)
    def observe(self, plan: PlanStep) -> Observation:
        session_id = str(plan.parameters.get("session_id") or "")
        page = self._pages.get(session_id)
        if page is None:
            return Observation(kind="browser", summary="No playground session is open yet.", data={"available": False})
        try:
            observation = observe_page(page)
            scenario_state = self._state(page)
            observation.data["available"] = True
            observation.data["scenario_state"] = scenario_state
        except Exception:
            return Observation(kind="browser", summary="Playground observation failed safely; the original plan will be used.", data={"available": False})
        return observation

    # ------------------------------------------------------------------
    # deterministic decision seam (mirrors BrowserTool.adapt's exact-name /
    # single-visible-candidate rules; reuses _stable_target for locators)
    def adapt(self, plan: PlanStep, observation: Observation) -> tuple[PlanStep, Decision]:
        if plan.parameters.get("action") != "click":
            return plan, Decision(kind="execute", reason="This step carries no semantic target to re-check.")
        planned = plan.parameters.get("target") or {}
        planned_name = str(planned.get("name") or "").strip()
        if not planned_name:
            return plan, Decision(kind="execute", reason="Planned target has no semantic name; the executor resolves it directly.")
        data = observation.data or {}
        if data.get("available") is not True:
            return plan, Decision(kind="execute", reason="No fresh observation is available; the original plan is used unchanged.")
        if data.get("elements_truncated"):
            return plan, Decision(kind="execute", reason="Observation was truncated; the original plan is used unchanged.")
        elements = data.get("elements") or []
        candidates = [
            element
            for element in elements
            if element.get("visible") and (element.get("role") == "button" or element.get("tag") == "button" or element.get("type") == "submit")
        ]
        exact = [element for element in candidates if str(element.get("name") or "").strip().casefold() == planned_name.casefold()]
        if exact:
            return plan, Decision(kind="execute", reason=f"Planned control {planned_name!r} is present in the fresh observation.")
        if len(candidates) == 1:
            candidate = candidates[0]
            target = BrowserTool._stable_target(candidate)
            if target is None:
                return plan, Decision(kind="fail", reason="Target not found: the only visible control has no stable selector.")
            adapted = plan.model_copy(deep=True)
            adapted.parameters["target"] = target
            return adapted, Decision(kind="retarget", reason=f"Planned control {planned_name!r} is gone; uniquely matched visible control {candidate.get('name')!r}.", target=target, replans=MAX_RETARGETS)
        if not candidates:
            return plan, Decision(kind="fail", reason="Target not found: no visible control matches the planned action.")
        return plan, Decision(kind="fail", reason=f"Ambiguous target: {len(candidates)} visible controls could match; refusing to guess.")

    # ------------------------------------------------------------------
    # execution seam
    def execute(self, plan: PlanStep, approved: bool = False) -> ToolResult:
        self.execute_calls += 1
        action = str(plan.parameters.get("action") or "")
        try:
            if action == "open":
                return self._open(plan)
            if action == "fill":
                return self._fill(plan)
            if action == "click":
                return self._click(plan, approved=approved)
            if action == "verify":
                return self._verify(plan)
            return ToolResult(status="failed", message=f"Playground action {action or 'missing'!r} is not yet supported.", output={"action": action})
        except Exception as error:
            return ToolResult(status="failed", message=f"Playground {action or 'action'} failed safely: {str(error)[:200]}", output={"action": action})

    def _open(self, plan: PlanStep) -> ToolResult:
        url = str(plan.parameters.get("url") or "")
        host = urlparse(url).hostname
        if host not in LOCAL_HOSTS:
            return ToolResult(status="failed", message="Non-local URLs are not yet supported by the playground.", output={"action": "open", "url": url})
        session_id = str(plan.parameters.get("session_id") or uuid.uuid4().hex)
        if session_id in self._pages:  # deterministic fresh state when reopened
            try:
                self._pages[session_id].close()
            except Exception:
                pass
            del self._pages[session_id]
        _, page = self._start_session(session_id)
        page.goto(url, timeout=GOTO_TIMEOUT_MS, wait_until="domcontentloaded")
        observation = observe_page(page)
        scenario_state = self._state(page)
        screenshot = self._screenshot(session_id, "open.png")
        checks: dict[str, bool] = {
            "page_reached": page.url.rstrip("/") == url.rstrip("/"),
            "scenario_state_loaded": isinstance(scenario_state, dict),
        }
        if "scenario" in plan.parameters:
            checks["scenario_matched"] = isinstance(scenario_state, dict) and scenario_state.get("scenario") == plan.parameters["scenario"]
        verification = VerificationResult.from_checks(checks, summary=f"Opened {page.url} and loaded the local playground scenario.", evidence=[screenshot or "", page.url]).model_dump()
        return ToolResult(
            status="completed",
            output={
                "action": "open",
                "session_id": session_id,
                "url": page.url,
                "screenshot_path": screenshot,
                "scenario_state": scenario_state,
                "observation": from_browser(observation.data).model_dump(),
                "verification": verification,
            },
        )

    def _fill(self, plan: PlanStep) -> ToolResult:
        page = self._page(plan)
        fields = plan.parameters.get("fields")
        if not isinstance(fields, list) or not fields or len(fields) > MAX_FIELDS:
            return ToolResult(status="failed", message=f"Playground fill with {len(fields) if isinstance(fields, list) else 0} fields is not yet supported (bounded to 1-{MAX_FIELDS} fields).", output={"action": "fill"})
        checks: dict[str, bool] = {}
        for field in fields:
            target = field.get("target") or {}
            kind = str(field.get("kind") or "text")
            value = field.get("value")
            locator = self._resolve(page, target)
            if kind == "checkbox":
                locator.check() if bool(value) else locator.uncheck()
                read_back: Any = bool(locator.is_checked())
                expected: Any = bool(value)
            elif kind == "select":
                locator.select_option(str(value))
                read_back = locator.input_value()
                expected = str(value)
            else:
                locator.fill(str(value))
                read_back = locator.input_value()
                expected = str(value)
            key = str(field.get("name") or "field")[:60]
            checks[f"field_{key}"] = read_back == expected
        screenshot = self._screenshot(str(plan.parameters.get("session_id") or ""), "fill.png")
        scenario_state = self._state(page)
        observation = observe_page(page)
        passed = all(checks.values())
        failed_keys = [key for key, ok in checks.items() if not ok]
        summary = f"All {len(checks)} playground field values match the requested values." if passed else f"Not verified: mismatch on {', '.join(failed_keys)}."
        verification = VerificationResult.from_checks(checks, summary=summary, evidence=[screenshot or "", page.url]).model_dump()
        return ToolResult(
            status="completed",
            output={
                "action": "fill",
                "url": page.url,
                "screenshot_path": screenshot,
                "scenario_state": scenario_state,
                "observation": from_browser(observation.data).model_dump(),
                "verification": verification,
            },
        )

    def _click(self, plan: PlanStep, approved: bool = False) -> ToolResult:
        page = self._page(plan)
        target = plan.parameters.get("target") or {}
        # Fast, honest stale-target check before acting (no slow locator wait).
        if target.get("name") and not target.get("css"):
            name = str(target["name"])
            matches = page.get_by_role("button", name=name, exact=True)
            count = matches.count()
            if count == 0:
                return ToolResult(status="failed", message="The planned control is not visible in the current state; a fresh observation can re-target.", output={"action": "click", "target": target, "scenario_state": self._state(page)})
            if count > 1:
                return ToolResult(status="failed", message="Ambiguous target: more than one visible control matches the planned name; refusing to guess.", output={"action": "click", "target": target, "scenario_state": self._state(page)})
        before = self._state(page) or {}
        before_version = int(before.get("version") or 0)
        self._resolve(page, target).click(timeout=ACTION_TIMEOUT_MS)
        after = self._state(page) or {}
        after_version = int(after.get("version") or 0)
        screenshot = self._screenshot(str(plan.parameters.get("session_id") or ""), "click.png")
        observation = observe_page(page)
        common = {
            "action": "click",
            "target": target,
            "approved": bool(approved),
            "scenario_state": after,
            "attempts": after.get("attempts"),
            "screenshot_path": screenshot,
            "url": page.url,
            "observation": from_browser(observation.data).model_dump(),
        }
        if after.get("last_action", {}).get("ok") is True:
            status_text = str(after.get("status") or "")
            checks = {"effect_observed": after_version > before_version, "action_reported_ok": True}
            verification = VerificationResult.from_checks(checks, summary=f"Playground accepted the action ({before_version}→{after_version}); post-action status: {status_text}", evidence=[screenshot or "", page.url]).model_dump()
            return ToolResult(status="completed", output={**common, "verification": verification})
        note = str(after.get("last_action", {}).get("note") or "The playground reported the action failed (deterministic).")
        return ToolResult(status="failed", message=note, output=common)

    def _verify(self, plan: PlanStep) -> ToolResult:
        page = self._page(plan)
        expect = plan.parameters.get("expect")
        wait_for = plan.parameters.get("wait_for") or {}
        if not isinstance(expect, dict) or not expect or not isinstance(wait_for, dict):
            return ToolResult(status="failed", message="Playground verify requires at least one expect value; verifying without expectations is not yet supported.", output={"action": "verify"})
        first_read = self._state(page)
        reobservations = 0
        final = first_read
        screenshot: str | None = None
        if wait_for:
            bounded_ms = min(max(int(plan.parameters.get("wait_timeout_ms") or DEFAULT_WAIT_TIMEOUT_MS), 1), MAX_WAIT_TIMEOUT_MS)
            pairs = ", ".join(f"{json.dumps(str(key))}: {json.dumps(value)}" for key, value in wait_for.items())
            expression = f"() => {{ const s = window.__playground && window.__playground.state; return !!s && Object.entries({{{pairs}}}).every(([k, v]) => s[k] === v); }}"
            try:
                page.wait_for_function(expression, timeout=bounded_ms)
                reobservations = 1
                final = self._state(page)
            except Exception:
                screenshot = self._screenshot(str(plan.parameters.get("session_id") or ""), "verify-timeout.png")
                expected_text = json.dumps(wait_for, sort_keys=True)
                verification = VerificationResult.from_checks({"expected_state_reached": False}, summary=f"Not verified: the deterministic state transition to {expected_text} did not occur within the bounded wait of {bounded_ms} ms.", evidence=[screenshot or "", page.url]).model_dump()
                return ToolResult(
                    status="failed",
                    message=f"Playground verification could not be verified within the bounded wait of {bounded_ms} ms; expected {expected_text}.",
                    output={"action": "verify", "first_read": first_read, "scenario_state": first_read, "reobservations": reobservations, "screenshot_path": screenshot, "url": page.url, "verification": verification},
                )
        checks = {f"state_{key}": (final or {}).get(key) == value for key, value in expect.items()}
        passed = all(checks.values())
        failed_keys = [key for key, ok in checks.items() if not ok]
        screenshot = self._screenshot(str(plan.parameters.get("session_id") or ""), "verify.png")
        observation = observe_page(page)
        summary = f"All {len(checks)} expected state values matched." if passed else f"Not verified: mismatch on {', '.join(failed_keys)}."
        verification = VerificationResult.from_checks(checks, summary=summary, evidence=[screenshot or "", page.url]).model_dump()
        output = {
            "action": "verify",
            "first_read": first_read,
            "scenario_state": final,
            "reobservations": reobservations,
            "screenshot_path": screenshot,
            "url": page.url,
            "observation": from_browser(observation.data).model_dump(),
            "verification": verification,
        }
        if passed:
            return ToolResult(status="completed", output=output)
        return ToolResult(status="failed", message=f"Playground verification failed: mismatch on {', '.join(failed_keys)}.", output=output)
