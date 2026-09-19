from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import DesktopObservation


def observe_desktop(runtime_dir: Path, max_windows: int = 12, max_controls: int = 60) -> DesktopObservation:
    runtime_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = runtime_dir / "desktop-observation.png"
    try:
        from PIL import ImageGrab
        image = ImageGrab.grab()
        image.save(screenshot_path)
        screen_size = {"width": image.width, "height": image.height}
    except Exception:
        screenshot_path = None
        screen_size = {}
    try:
        from pywinauto import Desktop
        desktop = Desktop(backend="uia")
        windows = desktop.windows(visible_only=True)
        window_items = [{"title": window.window_text()[:160], "control_type": window.element_info.control_type, "class_name": window.element_info.class_name} for window in windows[:max_windows]]
        controls: list[dict[str, Any]] = []
        active = None
        for window in windows[:max_windows]:
            if window.is_active():
                active = window.window_text()[:160]
            try:
                for control in window.descendants()[:max_controls - len(controls)]:
                    info = control.element_info
                    controls.append({"window": window.window_text()[:80], "name": info.name[:160], "value": control.window_text()[:500], "control_type": info.control_type, "automation_id": info.automation_id, "class_name": info.class_name, "enabled": control.is_enabled(), "visible": control.is_visible()})
            except Exception:
                continue
        return DesktopObservation(active_window=active, windows=window_items, controls=controls[:max_controls], screen_size=screen_size, screenshot=str(screenshot_path) if screenshot_path else None)
    except Exception:
        return DesktopObservation(screen_size=screen_size, screenshot=str(screenshot_path) if screenshot_path else None)
