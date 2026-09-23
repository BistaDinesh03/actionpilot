from __future__ import annotations

import re
from pathlib import Path
from threading import Event
from typing import Any

from .browser import BrowserSession
from .locator import resolve_locator
from .models import ApprovalGate, ExecutionContext, ProgressCallback, StepOutcome


class ConfirmationRequired(RuntimeError):
    pass


class ExecutionStopped(RuntimeError):
    pass


class BrowserExecutor:
    def __init__(self, runtime_dir: Path, progress: ProgressCallback | None = None, headless: bool = True) -> None:
        self.runtime_dir = runtime_dir
        self.progress = progress or (lambda _event, _index, _data: None)
        self.headless = headless
        self.session: BrowserSession | None = None

    @staticmethod
    def risk_level(step: dict[str, Any]) -> str:
        explicit = (step.get("risk_level") or "low").lower()
        if explicit == "high":
            return "high"
        action_type = (step.get("type") or "").lower()
        # Non-mutating step types cannot cause side effects. Mark them low.
        if action_type in ("assert", "wait", "navigate", "scroll", "press", "select", "check", "uncheck"):
            return "low"
        # For actions that can mutate state (click, submit, type), keep the text heuristic.
        text = f"{step.get('label', '')} {step.get('value', '')}".lower()
        high_words = ("purchase", "buy", "send", "delete", "publish", "submit", "checkout", "payment")
        return "high" if any(word in text for word in high_words) else "low"

    @staticmethod
    def substitute(value: Any, variables: dict[str, str]) -> Any:
        if not isinstance(value, str):
            return value
        result = value
        for key, replacement in variables.items():
            result = result.replace("{{" + key + "}}", replacement).replace("{" + key + "}", replacement)
        return result

    def _wait_if_paused(self, context: ExecutionContext) -> None:
        while context.pause_event.is_set() and not context.stop_event.is_set():
            context.stop_event.wait(0.1)
        if context.stop_event.is_set():
            raise ExecutionStopped("Run stopped by user")

    def execute(self, steps: list[dict[str, Any]], variables: dict[str, str] | None = None, stop_event: Event | None = None, pause_event: Event | None = None, gate: ApprovalGate | None = None) -> list[StepOutcome]:
        context = ExecutionContext(stop_event or Event(), pause_event or Event(), variables=variables or {})
        self.session = BrowserSession(self.runtime_dir, headless=self.headless)
        page = self.session.start()
        outcomes: list[StepOutcome] = []
        try:
            for index, raw_step in enumerate(steps):
                self._wait_if_paused(context)
                step = {key: self.substitute(value, context.variables) for key, value in raw_step.items()}
                if step.get("type") == "type" and "product" in context.variables:
                    step["value"] = context.variables["product"]
                if step.get("type") == "select" and any(key in context.variables for key in ("color", "size")):
                    step["value"] = context.variables.get("color", context.variables.get("size", step.get("value", "")))
                if self.risk_level(step) == "high":
                    if gate is None:
                        self.progress("waiting_confirmation", index, {"message": "Confirmation required"})
                        raise ConfirmationRequired("Confirmation required")
                    reason = gate(index, step)
                    if reason:
                        raise ExecutionStopped(reason)
                self.progress("step_started", index, {"step": step})
                _shot = self.session.screenshot(f"step-{index}.png")
                self.progress("step_screenshot", index, {"screenshot_path": _shot})
                try:
                    self.execute_step(page, step, context)
                    outcome = StepOutcome("completed", index, url=page.url, title=page.title())
                    outcomes.append(outcome)
                    verification = None
                    cart = page.locator("#cart")
                    if cart.count():
                        verification = {"cart_count": cart.text_content()}
                    self.progress("step_completed", index, {"url": page.url, "title": page.title(), "verification": verification})
                except Exception as error:
                    screenshot = self.session.screenshot(f"step-{index}.png")
                    outcome = StepOutcome("failed", index, str(error), screenshot, page.url, page.title())
                    outcomes.append(outcome)
                    self.progress("step_failed", index, {"error": str(error), "screenshot_path": screenshot, "url": page.url, "title": page.title()})
                    raise
            return outcomes
        finally:
            self.session.close()
            self.session = None

    def execute_step(self, page: Any, step: dict[str, Any], context: ExecutionContext) -> None:
        action_type = step["type"]
        target = step.get("target") or {}
        value = step.get("value")
        if action_type == "navigate":
            url = value or step.get("url")
            if not url or not re.match(r"^https?://", url):
                raise ValueError("Navigation URL must use http or https")
            page.goto(url, wait_until="domcontentloaded")
            return
        if action_type == "wait":
            if target:
                wait_ms = 10_000
                try:
                    wait_ms = int(value) if value is not None else 10_000
                except (TypeError, ValueError):
                    wait_ms = 10_000
                try:
                    locator, _strategy = resolve_locator(page, target, wait_ms)
                except Exception as error:
                    raise ValueError(f"wait step failed: target did not become visible within {wait_ms}ms ({error})") from error
                return
            page.wait_for_timeout(min(int(value or 500), 10_000))
            return
        if action_type == "assert":
            if not target:
                raise ValueError("assert step requires a target")
            assert_ms = 5_000
            try:
                assert_ms = int(value) if value is not None else 5_000
            except (TypeError, ValueError):
                assert_ms = 5_000
            try:
                locator, _strategy = resolve_locator(page, target, assert_ms)
            except Exception as error:
                raise AssertionError(f"assert step failed: target is not visible within {assert_ms}ms ({error})") from error
            return
        locator, _strategy = resolve_locator(page, target, context.timeout_ms)
        if action_type == "click" or action_type == "submit":
            locator.click()
        elif action_type == "type":
            # Real keyboard input: focus the field, clear any existing value,
            # then type character by character. locator.fill() does not emit
            # keydown/keypress/keyup events, which React/Vue/Angular controlled
            # inputs and validation libraries rely on. locator.type() emits
            # the full event sequence.
            locator.click()
            try:
                locator.press("Control+A")
                locator.press("Delete")
            except Exception:
                pass
            locator.type(value or "", delay=15)
        elif action_type == "press":
            locator.press(value or "Enter")
        elif action_type == "select":
            locator.select_option(value=value or "")
        elif action_type == "check":
            locator.check()
        elif action_type == "uncheck":
            locator.uncheck()
        elif action_type == "scroll":
            locator.scroll_into_view_if_needed()
            page.mouse.wheel(0, int(value or 600))
        else:
            raise ValueError(f"Unsupported browser action: {action_type}")
        page.wait_for_timeout(100)
