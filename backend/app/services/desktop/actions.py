from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from .models import DesktopAction, DesktopObservation
from .observer import observe_desktop

ALLOWLIST = {"notepad": "notepad.exe", "explorer": "explorer.exe", "chrome": "chrome.exe", "vscode": os.getenv("VSCODE_PATH", "Code.exe")}
PROCESSES: dict[str, subprocess.Popen[Any]] = {}


def launch(application_id: str, runtime_dir: Path) -> DesktopObservation:
    executable = ALLOWLIST.get(application_id.lower())
    if not executable:
        raise ValueError("Application is not on the ActionPilot allowlist")
    process = subprocess.Popen([executable], shell=False)
    PROCESSES[application_id.lower()] = process
    time.sleep(0.5)
    try:
        from pywinauto import Application
        application = Application(backend="uia").connect(process=process.pid, timeout=5)
        application.top_window().set_focus()
    except Exception:
        try:
            from pywinauto import Desktop
            candidates = [window for window in Desktop(backend="uia").windows(visible_only=True) if application_id.lower() in window.window_text().lower() or (application_id.lower() == "notepad" and window.element_info.class_name == "Notepad")]
            if candidates:
                candidates[-1].set_focus()
        except Exception:
            pass
    return observe_desktop(runtime_dir)


def _control(action: DesktopAction):
    from pywinauto import Desktop
    desktop = Desktop(backend="uia")
    target = action.target
    if not target:
        raise ValueError("A semantic desktop target is required")
    candidates = desktop.windows(visible_only=True)
    for window in candidates:
        controls = window.descendants()
        for control in controls:
            info = control.element_info
            if target.automation_id and info.automation_id == target.automation_id:
                return control
            if target.name and target.control_type and info.name == target.name and info.control_type == target.control_type:
                return control
            if target.name and info.name == target.name:
                return control
            if target.class_name and info.class_name == target.class_name:
                return control
    raise LookupError("Desktop control was not found using semantic metadata")


def _active_window():
    from pywinauto import Desktop
    windows = Desktop(backend="uia").windows(visible_only=True)
    for window in windows:
        try:
            if window.is_active():
                return window
        except Exception:
            continue
    raise LookupError("No active Windows application was found")


def execute(action: DesktopAction, runtime_dir: Path) -> DesktopObservation:
    if action.type == "launch_application":
        if not action.application_id:
            raise ValueError("application_id is required")
        return launch(action.application_id, runtime_dir)
    if action.type == "take_screenshot":
        return observe_desktop(runtime_dir)
    if action.type in {"type_text", "press_key", "hotkey"} and not action.target:
        control = _active_window()
        if action.type == "type_text":
            edits = [candidate for candidate in control.descendants() if candidate.element_info.control_type in {"Edit", "Document"}]
            if edits:
                control = edits[0]
    else:
        control = _control(action)
    if action.type == "focus_window":
        control.set_focus()
    elif action.type == "click":
        control.click_input()
    elif action.type == "double_click":
        control.double_click_input()
    elif action.type == "type_text":
        control.set_focus()
        import pyperclip
        pyperclip.copy(action.value or "")
        control.type_keys("^v")
    elif action.type == "press_key":
        control.set_focus()
        control.type_keys(action.value or "ENTER")
    elif action.type == "hotkey":
        control.set_focus()
        control.type_keys(action.value or "", with_spaces=True)
    elif action.type == "scroll":
        control.scroll(int(action.value or 1))
    elif action.type == "wait":
        time.sleep(min(float(action.value or 0.5), 10))
    return observe_desktop(runtime_dir)
